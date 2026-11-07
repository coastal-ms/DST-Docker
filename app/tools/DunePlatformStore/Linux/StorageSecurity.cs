using System.ComponentModel;
using System.Runtime.InteropServices;
using System.Runtime.Versioning;
using Microsoft.Win32.SafeHandles;

namespace DunePlatformStore;

// Docker's private state mount is the trust boundary. Different users cannot
// write its cache directory. Held no-follow descriptors and inode checks reject
// replacement; Linux descriptors do not provide Windows deny-rename sharing.
[SupportedOSPlatform("linux")]
internal static class StorageSecurity
{
    private const string ProductionRoot = "/data/state";
    private const string RelativeDatabase = "DuneServer/platform-cache/platform-cache-v1.sqlite";
    private const int AtFdcwd = -100, AtNoFollow = 0x100, AtEmptyPath = 0x1000;
    private const int NoFollow = 0x20000, CloseOnExec = 0x80000, DirectoryFlag = 0x10000;
    private const uint BasicStats = 0x7ff;

    internal static string GetDefaultDatabasePath() => ProductionRoot + "/" + RelativeDatabase;
    private static bool IsSelfTest() => Environment.GetEnvironmentVariable("DST_PLATFORM_SELF_TEST") == "1";

    private static string ValidateAllowedDatabasePath(string path)
    {
        var full = Path.GetFullPath(path);
        var expected = GetDefaultDatabasePath();
        var migration = full.StartsWith(expected + ".migration-", StringComparison.Ordinal) &&
                        full.EndsWith(".bak", StringComparison.Ordinal) && full.Length <= expected.Length + 64;
        if (!IsSelfTest() && full != expected && !migration)
            throw new UnauthorizedAccessException("The Linux cache path is fixed inside its private state volume.");
        return full;
    }

    internal static void EnsureProtectedDirectory(string databasePath)
    {
        using var lease = AcquireDirectories(ValidateAllowedDatabasePath(databasePath), true);
        var directory = Path.GetDirectoryName(databasePath)!;
        File.SetUnixFileMode(directory, UnixFileMode.UserRead | UnixFileMode.UserWrite | UnixFileMode.UserExecute);
        lease.RevalidateAll();
    }

    internal static StorageLease AcquireDatabase(string databasePath, bool readOnly)
    {
        var path = ValidateAllowedDatabasePath(databasePath);
        var lease = AcquireDirectories(path, false);
        try
        {
            lease.HoldDatabase(path, !readOnly);
            lease.HoldSidecars(path);
            lease.RevalidateAll();
            return lease;
        }
        catch { lease.Dispose(); throw; }
    }

    private static StorageLease AcquireDirectories(string databasePath, bool createMissing)
    {
        var root = IsSelfTest() ? Path.GetFullPath(Path.GetTempPath()).TrimEnd('/') : ProductionRoot;
        var parent = Path.GetDirectoryName(databasePath)!;
        var relative = Path.GetRelativePath(root, parent);
        if (relative == "." || relative == ".." || relative.StartsWith("../", StringComparison.Ordinal) || Path.IsPathRooted(relative))
            throw new UnauthorizedAccessException("The cache directory escapes its trusted state root.");
        var lease = new StorageLease(root);
        try
        {
            foreach (var component in relative.Split('/', StringSplitOptions.RemoveEmptyEntries))
                lease.HoldDirectory(component, createMissing);
            return lease;
        }
        catch { lease.Dispose(); throw; }
    }

    internal sealed class StorageLease : IDisposable
    {
        private readonly List<(string Path, SafeFileHandle Handle, FileIdentity Identity)> held = [];
        internal StorageLease(string root)
        {
            var handle = Open(AtFdcwd, root, DirectoryFlag | NoFollow | CloseOnExec);
            try
            {
                var identity = Inspect(handle);
                if (!IsSelfTest() && (identity.Uid != PrivilegeDrop.geteuid() || (identity.Mode & 0x12) != 0))
                    throw new UnauthorizedAccessException("The Linux state root must be owned and protected from other writers.");
                held.Add((root, handle, identity));
            }
            catch { handle.Dispose(); throw; }
        }

        internal void HoldDirectory(string component, bool create)
        {
            var parent = held[^1];
            var fd = parent.Handle.DangerousGetHandle().ToInt32();
            if (create && mkdirat(fd, component, 0x1c0) != 0 && Marshal.GetLastWin32Error() != 17)
                throw new Win32Exception(Marshal.GetLastWin32Error(), "The private cache directory could not be created.");
            Hold(parent.Path + "/" + component, Open(fd, component, DirectoryFlag | NoFollow | CloseOnExec), true);
        }

        internal void HoldDatabase(string path, bool createIfMissing) => HoldFile(path, createIfMissing);
        internal void HoldSidecars(string path)
        {
            HoldFile(path + "-wal", true);
            HoldFile(path + "-shm", true);
        }

        private void HoldFile(string path, bool create)
        {
            var directory = held.Last(item => (item.Identity.Mode & 0xf000) == 0x4000);
            if (Path.GetDirectoryName(path) != directory.Path)
                throw new UnauthorizedAccessException("The cache file is outside its held directory.");
            var handle = Open(directory.Handle.DangerousGetHandle().ToInt32(), Path.GetFileName(path),
                2 | NoFollow | CloseOnExec | (create ? 0x40 : 0));
            Hold(path, handle, false);
        }

        private void Hold(string path, SafeFileHandle handle, bool directory)
        {
            try
            {
                var identity = Inspect(handle);
                if ((identity.Mode & 0xf000) != (directory ? 0x4000 : 0x8000) ||
                    identity.Uid != PrivilegeDrop.geteuid() || (identity.Mode & 0x12) != 0 ||
                    (!directory && identity.Links != 1))
                    throw new UnauthorizedAccessException("Cache storage must be an owned, non-writable-by-others regular file or directory.");
                if (!directory && fchmod(handle.DangerousGetHandle().ToInt32(), 0x180) != 0)
                    throw new Win32Exception(Marshal.GetLastWin32Error(), "Cache file permissions could not be protected.");
                held.Add((path, handle, identity));
            }
            catch { handle.Dispose(); throw; }
        }

        internal void RevalidateAll()
        {
            foreach (var item in held)
            {
                if (statx(AtFdcwd, item.Path, AtNoFollow, BasicStats, out var current) != 0 ||
                    current.Inode != item.Identity.Inode || current.DeviceMajor != item.Identity.DeviceMajor ||
                    current.DeviceMinor != item.Identity.DeviceMinor || (current.Mode & 0xf000) != (item.Identity.Mode & 0xf000))
                    throw new UnauthorizedAccessException("The held cache path changed during the operation.");
                var pinned = Inspect(item.Handle);
                if (pinned.Uid != item.Identity.Uid || ((pinned.Mode & 0x12) != 0 && !(IsSelfTest() && item.Path == held[0].Path)) ||
                    ((pinned.Mode & 0xf000) == 0x8000 && pinned.Links != 1))
                    throw new UnauthorizedAccessException("The held cache storage permissions or links changed.");
            }
        }

        public void Dispose()
        {
            for (var index = held.Count - 1; index >= 0; --index) held[index].Handle.Dispose();
            held.Clear();
        }
    }

    internal static bool SelfTestHeldHandleRace(string root)
    {
        var path = Path.Combine(root, "handle-race", "platform-cache-v1.sqlite");
        EnsureProtectedDirectory(path);
        using var lease = AcquireDatabase(path, false);
        File.Move(path, path + ".moved");
        var fileRejected = false;
        try { lease.RevalidateAll(); } catch (UnauthorizedAccessException) { fileRejected = true; }
        File.Move(path + ".moved", path);
        var parent = Path.GetDirectoryName(path)!;
        Directory.Move(parent, parent + "-moved");
        var directoryRejected = false;
        try { lease.RevalidateAll(); } catch (UnauthorizedAccessException) { directoryRejected = true; }
        Directory.Move(parent + "-moved", parent);
        return fileRejected && directoryRejected;
    }

    private static SafeFileHandle Open(int parent, string path, int flags)
    {
        var fd = openat(parent, path, flags, 0x180);
        if (fd < 0) throw new Win32Exception(Marshal.GetLastWin32Error(), "The cache path could not be opened without following links.");
        return new SafeFileHandle((IntPtr)fd, true);
    }
    private static FileIdentity Inspect(SafeFileHandle handle)
    {
        if (statx(handle.DangerousGetHandle().ToInt32(), "", AtEmptyPath | AtNoFollow, BasicStats, out var identity) != 0 ||
            (identity.Mask & 0x10f) != 0x10f)
            throw new Win32Exception(Marshal.GetLastWin32Error(), "The held cache identity could not be inspected.");
        return identity;
    }

    // Linux statx ABI is fixed-size; unused timestamps/reserved fields remain
    // padding. See linux/stat.h and statx(2), including AT_EMPTY_PATH.
    [StructLayout(LayoutKind.Explicit, Size = 256)]
    private struct FileIdentity
    {
        [FieldOffset(0)] internal uint Mask;
        [FieldOffset(16)] internal uint Links;
        [FieldOffset(20)] internal uint Uid;
        [FieldOffset(28)] internal ushort Mode;
        [FieldOffset(32)] internal ulong Inode;
        [FieldOffset(136)] internal uint DeviceMajor;
        [FieldOffset(140)] internal uint DeviceMinor;
    }
    [DllImport("libc", SetLastError = true)] private static extern int openat(int dirfd, string path, int flags, uint mode);
    [DllImport("libc", SetLastError = true)] private static extern int mkdirat(int dirfd, string path, uint mode);
    [DllImport("libc", SetLastError = true)] private static extern int fchmod(int fd, uint mode);
    [DllImport("libc", SetLastError = true)] private static extern int statx(int dirfd, string path, int flags, uint mask, out FileIdentity data);
}
