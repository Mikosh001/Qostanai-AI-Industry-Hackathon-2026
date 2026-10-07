using System.Management;
using Microsoft.Win32;

internal static partial class Program {
    // USB hard disks can report DriveType.Fixed. Include their mapped logical volumes.
    static HashSet<string> StorageVolumes() {
        var volumes=DriveInfo.GetDrives().Where(d=>d.DriveType==DriveType.Removable)
            .Select(d=>d.RootDirectory.FullName).ToHashSet(StringComparer.OrdinalIgnoreCase);
        using var search=new ManagementObjectSearcher("SELECT DeviceID,InterfaceType,PNPDeviceID FROM Win32_DiskDrive");
        using var disks=search.Get();
        foreach(ManagementObject disk in disks)using(disk) {
            var pnp=disk["PNPDeviceID"]?.ToString()??"";
            if(disk["InterfaceType"]?.ToString()!="USB"&&!pnp.StartsWith("USBSTOR",StringComparison.OrdinalIgnoreCase))continue;
            using var partitions=disk.GetRelated("Win32_DiskPartition");
            foreach(ManagementObject partition in partitions)using(partition) {
                using var logical=partition.GetRelated("Win32_LogicalDisk");
                foreach(ManagementObject drive in logical)using(drive) {
                    if(drive["DeviceID"] is string letter)volumes.Add(letter+"\\");
                }
            }
        }
        return volumes;
    }
    static void ValidateStorage(int epoch) {
        bool denied=true;string? failure=null;HashSet<string> volumes;
        try {
            using var key=Registry.LocalMachine.OpenSubKey(StorageKey,false);
            if(key?.GetValue("Deny_All") is not int value||value!=1)failure="storage_policy_changed";
            volumes=StorageVolumes();
            foreach(var volume in volumes) {
                try {
                    using var entries=Directory.EnumerateFileSystemEntries(volume).GetEnumerator();
                    entries.MoveNext(); // Empty readable volumes must also fail.
                    failure="readable_usb_volume: "+volume;break;
                } catch(UnauthorizedAccessException) { }
                  catch(IOException) {denied=false;}
            }
            if(CachedStorage.Count>0&&volumes.Count==0)denied=false;
        } catch(Exception ex) {volumes=new();denied=false;LastError=ex.Message;}
        lock(RestrictionSync) {
            // A completed old WMI scan cannot certify or release a newer exam.
            if(!Active||!StorageEnforced||epoch!=Volatile.Read(ref StorageEpoch))return;
            StorageReady=failure==null&&denied;
            if(failure!=null) {
                LastError="USB қорғанысы расталмады: "+failure;
                Emit(new{type="event",kind="storage_enforcement_failed",detail=new{reason=failure,blocked=false}});
                Release();return;
            }
            if(StorageReady&&volumes.Count>0&&epoch!=Volatile.Read(ref StorageProofEpoch)) {
                Volatile.Write(ref StorageProofEpoch,epoch);
                Emit(new{type="event",kind="storage_denial_verified",detail=new{volumes,denied=true}});
            }
        }
    }
}
