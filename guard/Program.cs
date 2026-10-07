using System.Diagnostics;
using System.Management;
using System.Runtime.InteropServices;
using System.Security.Principal;
using System.Text;
using System.Text.Json;
using Microsoft.Win32;

// Stdin/stdout IPC only. No unauthenticated TCP service. Every restriction has a 10s lease.
internal static partial class Program {
    static readonly object Sync = new();
    static readonly object RestrictionSync = new();
    static volatile bool Active, BlockKeyboard, StorageEnforced, CaptureProtected, Closing;
    static int StorageEpoch, StorageProofEpoch = -1;
    static volatile bool StorageReady;
    static bool AllowCopy;
    static int WatchBusy;
    static long Lease = Environment.TickCount64;
    static nint Hook;
    static Thread? HookThread;
    static uint HookThreadId;
    static Native.HookProc? Callback;
    static readonly HashSet<string> PreviousDrives = new();
    static readonly HashSet<string> PreviousDevices = new();
    static readonly HashSet<string> PreviousForbidden = new();
    static List<object> CachedStorage = new();
    static List<object> CachedPeripherals = new();
    static HashSet<string> Forbidden = new(StringComparer.OrdinalIgnoreCase);
    static string JournalPath = "";
    static string? LastError;
    static nint ExamWindow;
    const string StorageKey = @"SOFTWARE\Policies\Microsoft\Windows\RemovableStorageDevices";
    record StorageBackup(bool Existed, int? DenyAll);
    static StorageBackup? Backup;
    static void Emit(object value) { lock(Sync) { Console.WriteLine(JsonSerializer.Serialize(value)); Console.Out.Flush(); } }
    static bool Admin() => new WindowsPrincipal(WindowsIdentity.GetCurrent()).IsInRole(WindowsBuiltInRole.Administrator);
    static async Task Main(string[] args) {
        if(args.Contains("--self-test-windows")){Environment.ExitCode=WindowRegression()?0:1;return;}
        if(args.Contains("--test-target")){await Task.Delay(30000);return;}
        if(args.Contains("--self-test-close")) {
            using var target=Process.Start(new ProcessStartInfo(Environment.ProcessPath!,"--test-target"){UseShellExecute=false,CreateNoWindow=true})!;
            await Task.Delay(300);CloseProcess(target,false,false);
            var passed=target.WaitForExit(2000);Emit(new{type="self_test_close",passed,target="own isolated child only",screen_capture=false});
            Environment.ExitCode=passed?0:1;return;
        }
        if(args.Contains("--self-test")) {
            var checks=new[]{KeyBlocked(0x09,false,true),KeyBlocked(0x43,true,false),KeyBlocked(0x5B,false,false),!KeyBlocked(0x41,false,false),!KeyBlocked(0x43,false,false)};
            UpdateParents();var parentSnapshot=Parents.ContainsKey(Environment.ProcessId);var desktop=InputDesktopAvailable();
            var topology=LauncherRegression();
            Emit(new{type="self_test",passed=checks.All(x=>x)&&parentSnapshot&&topology,checks=checks.Length,parent_snapshot=parentSnapshot,launcher_topology=topology,input_desktop_default=desktop});Environment.ExitCode=checks.All(x=>x)&&parentSnapshot&&topology?0:1;return;
        }
        if (!OperatingSystem.IsWindows()) { Emit(new {type="fatal",error="Windows required"});return; }
        var data = Environment.GetEnvironmentVariable("SERGEK_GUARD_DATA") ?? Path.Combine(AppContext.BaseDirectory,"runtime");
        Directory.CreateDirectory(data);JournalPath=Path.Combine(data,"guard-recovery.json");
        RemoteJournalPath=Path.Combine(data,"remote-recovery.json");
        RecoverRemote();
        Recover();
        AppDomain.CurrentDomain.ProcessExit += (_,_) => Release();
        Console.CancelKeyPress += (_,e) => {e.Cancel=true;Closing=true;Release();};
        using var timer=new System.Threading.Timer(_=>Watch(),null,1000,1000);
        using var leaseTimer=new System.Threading.Timer(_=>CheckLease(),null,500,500);
        using var applicationTimer=new System.Threading.Timer(_=>WatchApplications(),null,200,200);
        Emit(new {type="ready",admin=Admin(),recovery_pending=File.Exists(JournalPath),error=LastError});
        try {
            string? line;
            while (!Closing && (line=await Console.In.ReadLineAsync())!=null) {
                try {
                    using var doc=JsonDocument.Parse(line);var root=doc.RootElement;
                    var command=root.GetProperty("command").GetString();
                    var id=root.TryGetProperty("id",out var idValue)?idValue.GetString():null;
                    if(command=="heartbeat") {Lease=Environment.TickCount64;Emit(new {type="response",id,status=Status()});}
                    else if(command=="probe") {
                        // WMI runs in the independent watcher, never in the lease IPC queue.
                        SetForbidden(root);Emit(new {type="response",id,status=Status()});
                    }
                    else if(command=="activate") {
                        lock(RestrictionSync) {
                        Release();SetForbidden(root);
                        ExamWindow=root.TryGetProperty("window",out var window)?(nint)window.GetInt64():0;
                        LastError=null;
                        try {
                            ConfigureApplications(root);
                            if(root.TryGetProperty("remote",out var remote)&&remote.GetBoolean())ApplyRemote();
                            if(File.Exists(JournalPath))throw new IOException("Previous storage policy recovery is pending.");
                            var storage=root.TryGetProperty("usb",out var usb)&&usb.GetBoolean();
                            if(storage) ApplyStorage();
                            BlockKeyboard=root.TryGetProperty("keyboard",out var keyboard)&&keyboard.GetBoolean();
                            AllowCopy=root.TryGetProperty("copy_paste",out var copy)&&copy.GetBoolean();
                            if(BlockKeyboard) StartHook();
                            CaptureProtected=ExamWindow!=0&&Native.GetWindowDisplayAffinity(ExamWindow,out var affinity)&&affinity==0x11;
                            Active=true;Lease=Environment.TickCount64;
                        } catch(Exception ex) {LastError=ex.Message;Release();}
                        }
                        Emit(new {type="response",id,status=Status()});
                    }
                    else if(command=="monitor") {lock(RestrictionSync){Release();SetForbidden(root);Active=true;Lease=Environment.TickCount64;}Emit(new {type="response",id,status=Status()});}
                    else if(command=="release") {Release();Emit(new {type="response",id,status=Status()});}
                    else if(command=="shutdown") {Release();Closing=true;Emit(new {type="response",id,status=Status()});}
                } catch(Exception ex) {Emit(new {type="error",error=ex.Message});}
            }
        } finally {Closing=true;Release();}
    }
    static void SetForbidden(JsonElement root) {
        if(root.TryGetProperty("forbidden",out var list)) Forbidden=list.EnumerateArray().Select(x=>x.GetString()??"").ToHashSet(StringComparer.OrdinalIgnoreCase);
    }
    static List<object> StorageDevices() {
        var result=new List<object>();
        try {
            using var search=new ManagementObjectSearcher("SELECT DeviceID,Model,PNPDeviceID,InterfaceType FROM Win32_DiskDrive");
            using var collection=search.Get();
            foreach(ManagementObject device in collection) {
                using(device) {
                var pnp=device["PNPDeviceID"]?.ToString()??"";
                if(device["InterfaceType"]?.ToString()=="USB" || pnp.StartsWith("USBSTOR",StringComparison.OrdinalIgnoreCase))
                    result.Add(new {id=device["DeviceID"]?.ToString(),name=device["Model"]?.ToString(),pnp,kind="storage"});
                }
            }
        } catch(Exception ex) {LastError=ex.Message;}
        return result;
    }
    static List<object> PeripheralDevices() {
        var result=new List<object>();
        try {
            using var search=new ManagementObjectSearcher("SELECT DeviceID,Name,PNPClass FROM Win32_PnPEntity WHERE Present=True");
            using var collection=search.Get();
            foreach(ManagementObject device in collection) {
                using(device) {
                var id=device["DeviceID"]?.ToString()??"";var kind=device["PNPClass"]?.ToString()??"";
                if(id.StartsWith("USB\\",StringComparison.OrdinalIgnoreCase)||kind is "WPD" or "AudioEndpoint" or "Camera" or "Monitor")
                    result.Add(new {id,name=device["Name"]?.ToString(),kind});
                }
            }
        } catch { }
        return result;
    }
    static List<string> ForbiddenProcesses() {
        var result=new List<string>();
        foreach(var process in Process.GetProcesses()) {
            try {var name=process.ProcessName+".exe";if(Forbidden.Contains(name))result.Add(name);} catch {} finally{process.Dispose();}
        }
        return result.Distinct().ToList();
    }
    static object Status() => new {
        available=true,active=Active,admin=Admin(),storage_policy_applied=StorageEnforced,storage_enforced=StorageEnforced&&Volatile.Read(ref StorageEpoch)==Volatile.Read(ref StorageProofEpoch),
        storage_ready=StorageEnforced&&StorageReady,storage_check_pending=StorageEnforced&&!StorageReady,
        storage_validation=StorageEnforced&&StorageReady?(CachedStorage.Count==0?"policy applied; no attached USB storage":"attached volumes denied"):"not ready",
        // Low-level hook is narrower than Windows Keyboard Filter; SAS is explicitly unsupported.
        keyboard_enforced=Hook!=0&&BlockKeyboard,
        keyboard_scope="Alt/Win chords, function keys, capture keys, unapproved Ctrl chords; Ctrl+Alt+F12 recovery; not Ctrl+Alt+Del",
        application_enforced=Active&&CloseApplications, remote_enforced=RemoteEnforced,
        unapproved_applications=Active&&CloseApplications?UnapprovedWindows():new List<object>(),
        remote_session=Native.GetSystemMetrics(0x1000)!=0,
        capture_protected=ExamWindow!=0&&Native.GetWindowDisplayAffinity(ExamWindow,out var affinity)&&affinity==0x11,lease_seconds=Math.Max(0,10-(Environment.TickCount64-Lease)/1000),
        storage_devices=CachedStorage,peripherals=CachedPeripherals,forbidden_processes=ForbiddenProcesses(),
        recovery_pending=File.Exists(JournalPath),error=LastError
    };
    static void ApplyStorage() {
        if(!Admin())throw new InvalidOperationException("USB restriction requires an administrator-authorized managed computer.");
        using var original=Registry.LocalMachine.OpenSubKey(StorageKey,false);
        Backup=new StorageBackup(original!=null,original?.GetValue("Deny_All") is int value?value:null);
        File.WriteAllText(JournalPath,JsonSerializer.Serialize(Backup));
        using var key=Registry.LocalMachine.CreateSubKey(StorageKey,true);
        key.SetValue("Deny_All",1,RegistryValueKind.DWord);key.Flush();
        if(key.GetValue("Deny_All") is not int actual||actual!=1)throw new IOException("Storage policy did not persist.");
        // This reports policy application, not proof of access denial on every driver.
        Interlocked.Increment(ref StorageEpoch);StorageReady=false;StorageEnforced=true;
    }
    static void Recover() {
        if(!File.Exists(JournalPath))return;
        try {Backup=JsonSerializer.Deserialize<StorageBackup>(File.ReadAllText(JournalPath));RestoreStorage();}
        catch(Exception ex){LastError="Recovery requires administrator: "+ex.Message;}
    }
    static void RestoreStorage() {
        if(Backup==null)return;
        using var key=Registry.LocalMachine.OpenSubKey(StorageKey,true);
        if(key!=null) {
            if(Backup.DenyAll is int previous)key.SetValue("Deny_All",previous,RegistryValueKind.DWord);
            else key.DeleteValue("Deny_All",false);
            key.Flush();
        }
        File.Delete(JournalPath);Backup=null;StorageEnforced=false;StorageReady=false;Interlocked.Increment(ref StorageEpoch);
    }
    static void StartHook() {
        using var ready=new ManualResetEventSlim();
        HookThread=new Thread(()=>{
            HookThreadId=Native.GetCurrentThreadId();Callback=KeyCallback;
            // Create the thread message queue before reporting ready, so WM_QUIT cannot be lost.
            Native.PeekMessage(out var initialMessage,0,0,0,0);
            Hook=Native.SetWindowsHookEx(13,Callback,Native.GetModuleHandle(null),0);
            ready.Set();
            if(Hook==0)return;
            while(Native.GetMessage(out var message,0,0,0)>0){Native.TranslateMessage(ref message);Native.DispatchMessage(ref message);}
            Native.UnhookWindowsHookEx(Hook);Hook=0;
        }){IsBackground=true};
        HookThread.Start();
        if(!ready.Wait(3000)||Hook==0)throw new IOException("Keyboard hook unavailable.");
    }
    static nint KeyCallback(int code,nint wParam,nint lParam) {
        if(code<0||!Active||!BlockKeyboard)return Native.CallNextHookEx(Hook,code,wParam,lParam);
        var key=Marshal.PtrToStructure<Native.Keyboard>(lParam);var vk=(int)key.vkCode;
        var down=wParam==0x100||wParam==0x104;
        var ctrl=(Native.GetAsyncKeyState(0x11)&0x8000)!=0;
        var alt=(Native.GetAsyncKeyState(0x12)&0x8000)!=0;
        // An always-available physical recovery sequence. Logs are preserved.
        if(down&&ctrl&&alt&&vk==0x7B) {
            BlockKeyboard=false;ThreadPool.QueueUserWorkItem(_=>{Emit(new{type="event",kind="emergency_release",detail=new{sequence="Ctrl+Alt+F12"}});Release();});
            return Native.CallNextHookEx(Hook,code,wParam,lParam);
        }
        bool blocked=KeyBlocked(vk,ctrl,alt,AllowCopy) || (!AllowCopy&&(Native.GetAsyncKeyState(0x10)&0x8000)!=0&&vk is 0x2D or 0x2E);
        if(blocked) {
            if(down)ThreadPool.QueueUserWorkItem(_=>Emit(new{type="event",kind="shortcut_blocked",detail=new{vk,ctrl,alt,blocked=true}}));
            return 1;
        }
        return Native.CallNextHookEx(Hook,code,wParam,lParam);
    }
    static void Watch() {
        if(Interlocked.Exchange(ref WatchBusy,1)!=0)return;
        try { WatchCore(); } catch(Exception ex) {LastError=ex.Message;} finally {Interlocked.Exchange(ref WatchBusy,0);}
    }
    static void WatchCore() {
        if(Closing||!Active)return;
        var drives=StorageDevices();CachedStorage=drives;var ids=drives.Select(x=>JsonSerializer.Serialize(x)).ToHashSet();
        if(Active) {
            var storageEpoch=Volatile.Read(ref StorageEpoch);
            if(StorageEnforced)ValidateStorage(storageEpoch);
            foreach(var value in ids.Except(PreviousDrives))Emit(new{type="event",kind="usb_connected",detail=new{device=JsonSerializer.Deserialize<JsonElement>(value),policy_applied=StorageEnforced}});
            foreach(var value in PreviousDrives.Except(ids))Emit(new{type="event",kind="usb_removed",detail=new{device=JsonSerializer.Deserialize<JsonElement>(value)}});
            var processes=ForbiddenProcesses().ToHashSet();
            foreach(var name in processes.Except(PreviousForbidden))Emit(new{type="event",kind="forbidden_process",detail=new{name,blocked=false}});
            PreviousForbidden.Clear();PreviousForbidden.UnionWith(processes);
        }
        PreviousDrives.Clear();PreviousDrives.UnionWith(ids);
        if(Environment.TickCount64/1000%4==0) {
            CachedPeripherals=PeripheralDevices();var devices=CachedPeripherals.Select(x=>JsonSerializer.Serialize(x)).ToHashSet();
            if(Active) foreach(var value in devices.Except(PreviousDevices))Emit(new{type="event",kind="peripheral_connected",detail=new{device=JsonSerializer.Deserialize<JsonElement>(value)}});
            PreviousDevices.Clear();PreviousDevices.UnionWith(devices);
        }
    }
    static void CheckLease() {
        if(Active&&Environment.TickCount64-Lease>10000){Release();Emit(new{type="event",kind="guard_lost",detail=new{reason="lease_expired",restrictions_released=true}});}
    }
    static bool KeyBlocked(int vk,bool ctrl,bool alt,bool allowCopy=false) {
        if(vk is 0x10 or 0x11 or 0x12 or 0xA0 or 0xA1 or 0xA2 or 0xA3 or 0xA4 or 0xA5)return false;
        if(vk is 0x5B or 0x5C or 0x2C or 0x1B || vk>=0x70&&vk<=0x87 || alt)return true;
        if(!ctrl)return false;
        if(vk is 0x41 or 0x5A or 0x59 or 0x25 or 0x27 or 0x08 or 0x2E)return false;
        if(allowCopy&&vk is 0x43 or 0x56 or 0x58)return false;
        return true;
    }
    static void Release() {
        lock(RestrictionSync) {
        Active=false;BlockKeyboard=false;
        CloseApplications=false;
        if(HookThreadId!=0)Native.PostThreadMessage(HookThreadId,0x12,0,0);
        if(HookThread!=null&&HookThread!=Thread.CurrentThread)HookThread.Join(1500);
        HookThread=null;HookThreadId=0;
        CaptureProtected=false;
        try {RestoreStorage();} catch(Exception ex){LastError=ex.Message;}
        try {RestoreRemote();} catch(Exception ex){LastError="Remote recovery: "+ex.Message;}
        }
    }
}

internal static partial class Native {
    internal delegate nint HookProc(int code,nint wParam,nint lParam);
    [StructLayout(LayoutKind.Sequential)]internal struct Keyboard{public uint vkCode,scanCode,flags,time;public nuint extra;}
    [StructLayout(LayoutKind.Sequential)]internal struct Message{public nint hwnd;public uint message;public nuint wParam;public nint lParam;public uint time;public int x,y;public uint lPrivate;}
    [DllImport("user32.dll",SetLastError=true)]internal static extern nint SetWindowsHookEx(int id,HookProc callback,nint module,uint thread);
    [DllImport("user32.dll")]internal static extern bool UnhookWindowsHookEx(nint hook);
    [DllImport("user32.dll")]internal static extern nint CallNextHookEx(nint hook,int code,nint wp,nint lp);
    [DllImport("user32.dll")]internal static extern short GetAsyncKeyState(int key);
    [DllImport("user32.dll")]internal static extern int GetMessage(out Message message,nint hwnd,uint min,uint max);
    [DllImport("user32.dll")]internal static extern bool PeekMessage(out Message message,nint hwnd,uint min,uint max,uint remove);
    [DllImport("user32.dll")]internal static extern bool TranslateMessage(ref Message message);
    [DllImport("user32.dll")]internal static extern nint DispatchMessage(ref Message message);
    [DllImport("user32.dll")]internal static extern bool PostThreadMessage(uint id,uint msg,nuint wp,nint lp);
    [DllImport("kernel32.dll")]internal static extern uint GetCurrentThreadId();
    [DllImport("kernel32.dll",CharSet=CharSet.Unicode)]internal static extern nint GetModuleHandle(string? module);
    [DllImport("user32.dll",SetLastError=true)]internal static extern bool SetWindowDisplayAffinity(nint hwnd,uint affinity);
    [DllImport("user32.dll",SetLastError=true)]internal static extern bool GetWindowDisplayAffinity(nint hwnd,out uint affinity);
}
