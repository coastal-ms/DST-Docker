# Docker storage on Windows WSL

DST Docker stores its game files and Docker volumes inside the Linux distribution. Its virtual disk grows as files are added, up to the configured maximum; growth also needs free space on the Windows drive holding the distribution.

Check space with `df -h / /var/lib/docker` inside the distribution and check free space on the Windows drive. A large virtual capacity does not reserve that amount on Windows.

If the distribution reaches its virtual capacity and the Windows drive has enough free space, use Microsoft's supported WSL resize procedure. Finish updates and backups, then stop the battlegroup and hosting. In Windows PowerShell, run `wsl --shutdown`, then `wsl --manage <distribution-name> --resize <new-size>` (for example, `wsl --manage Ubuntu --resize 1500GB`). This requires a WSL version supporting `--manage --resize`. Start hosting again and verify `df -h /` reports the new capacity. Do not resize during server updates or other WSL work.

See [Microsoft: manage WSL disk space](https://learn.microsoft.com/en-us/windows/wsl/disk-space) for prerequisites and the manual alternative on older WSL versions. Native Linux and Linux VMs use their host's storage expansion procedure; DST does not modify host partitions.
