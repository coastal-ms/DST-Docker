using System.Runtime.InteropServices;

namespace DunePlatformStore;

internal static class PrivilegeDrop
{
    internal static int? EnsureUnelevated(string[] args)
    {
        if (!OperatingSystem.IsLinux() || IsElevated())
            throw new UnauthorizedAccessException("The Linux cache helper requires a non-root Linux process.");
        return null;
    }

    internal static bool IsElevated() => geteuid() == 0;

    internal static bool SelfTestInheritableStandardHandles() =>
        Enumerable.Range(0, 3).All(fd => fcntl(fd, 1) is var flags && flags >= 0 && (flags & 1) == 0);

    [DllImport("libc", SetLastError = true)] internal static extern uint geteuid();
    [DllImport("libc", SetLastError = true)] private static extern int fcntl(int fd, int command);
}
