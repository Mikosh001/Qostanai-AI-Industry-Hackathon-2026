using System.Diagnostics;
using System.Drawing;
using System.Drawing.Imaging;
using System.Management;
using System.Runtime.InteropServices;
using System.ServiceProcess;
using System.Text;
using System.Text.Json;
using Microsoft.Win32;
using System.ComponentModel;

internal static partial class Program {
    static volatile bool CloseApplications, RemoteEnforced;
    static int ApplicationBusy;
    static string RemoteJournalPath="";
    record RemoteBackup(string Name,bool Running,int Start);
    static List<RemoteBackup> RemoteBackups=new();
    static readonly string[] RemoteServices={"UmRdpService","SessionEnv","TermService"};
    static readonly HashSet<string> RemoteExecutables=new(StringComparer.OrdinalIgnoreCase){
        "anydesk.exe","anydesk_service.exe","teamviewer.exe","teamviewer_service.exe","rustdesk.exe",
        "quickassist.exe","msra.exe","mstsc.exe","vncserver.exe","winvnc.exe","tvnserver.exe",
        "parsecd.exe","aeroadmin.exe","screenconnect.clientservice.exe","strwinclt.exe","logmein.exe","dwagent.exe"};
    static readonly int OwnSession=Process.GetCurrentProcess().SessionId;
    static HashSet<int> TrustedPids=new();
    static Dictionary<int,int> Parents=new();
    static long LastParentUpdate,LastApplicationScan,LastRemoteCheck;
    static int LastForeground;
    static int ExamOwnerPid;
    static readonly HashSet<string> Critical=new(StringComparer.OrdinalIgnoreCase){
        "System","Registry","smss","csrss","wininit","services","lsass","winlogon","dwm",
        "fontdrvhost","svchost","sihost","ctfmon","taskhostw","conhost","RuntimeBroker",
        "ShellExperienceHost","StartMenuExperienceHost","SearchHost","TextInputHost",
        "SecurityHealthSystray","SecurityHealthService","WUDFHost","audiodg","spoolsv"};
    static void ConfigureApplications(JsonElement root) {
        CloseApplications=root.TryGetProperty("applications",out var setting)&&setting.GetBoolean();
        TrustedPids=new(){Environment.ProcessId};
        if(root.TryGetProperty("trusted_pids",out var pids))foreach(var pid in pids.EnumerateArray())TrustedPids.Add(pid.GetInt32());
        ExamOwnerPid=root.TryGetProperty("owner_pid",out var owner)?owner.GetInt32():0;
        if(ExamOwnerPid>0)TrustedPids.Add(ExamOwnerPid);
        UpdateParents();LastForeground=0;
    }
    static void UpdateParents() {
        var parents=new Dictionary<int,int>();var snapshot=Native.CreateToolhelp32Snapshot(2,0);
        if(snapshot==(nint)(-1))return;
        try {
            var row=new Native.ProcessEntry{size=(uint)Marshal.SizeOf<Native.ProcessEntry>()};
            if(Native.Process32First(snapshot,ref row))do{parents[(int)row.pid]=(int)row.parent;}while(Native.Process32Next(snapshot,ref row));
            Parents=parents;LastParentUpdate=Environment.TickCount64;
        } finally {Native.CloseHandle(snapshot);}
    }
    static bool Trusted(int pid) {
        var seen=new HashSet<int>();
        while(pid>0&&seen.Add(pid)) {
            if(TrustedPids.Contains(pid))return true;
            if(!Parents.TryGetValue(pid,out pid))break;
        }
        return false;
    }
    static bool ExamLauncher(int pid) {
        var seen=new HashSet<int>();var cursor=ExamOwnerPid;
        while(cursor>0&&seen.Add(cursor)&&Parents.TryGetValue(cursor,out cursor))
            if(cursor==pid)return true;
        return false;
    }
    static void WatchApplications() {
        if(!Active||Interlocked.Exchange(ref ApplicationBusy,1)!=0)return;
        try {
          lock(RestrictionSync) {
            if(!Active)return;
            if(CloseApplications&&!InputDesktopAvailable()) {
                Emit(new{type="event",kind="protected_desktop_left",detail=new{reason="input_desktop_changed",blocked=false}});Release();return;
            }
            if(Environment.TickCount64-LastParentUpdate>1500)UpdateParents();
            var window=Native.GetForegroundWindow();Native.GetWindowThreadProcessId(window,out var foreground);
            if((int)foreground!=LastForeground) {
                LastForeground=(int)foreground;
                try {using var process=Process.GetProcessById(LastForeground);
                    var trusted=Trusted(process.Id);
                    Emit(new{type="event",kind="foreground_changed",detail=new{pid=process.Id,name=process.ProcessName+".exe",title=WindowTitle(window),trusted,prevention_active=CloseApplications,screen_jpeg=!trusted&&!CloseApplications?ScreenImage():null}});
                } catch { }
            }
            if(Environment.TickCount64-LastApplicationScan<400)return;
            LastApplicationScan=Environment.TickCount64;
            var scanStart=Environment.TickCount64;
            var visibleWindows=VisibleWindows();
            foreach(var process in Process.GetProcesses()) {
                using(process) {
                    try {
                        var name=process.ProcessName;var forbidden=Forbidden.Contains(name+".exe");
                        var remote=RemoteEnforced&&RemoteExecutables.Contains(name+".exe");
                        if(Trusted(process.Id)||process.SessionId!=OwnSession&&!remote)continue;
                        var visible=ApplicationWindows(process.Id,name,visibleWindows).Count!=0;
                        if((CloseApplications&&visible||forbidden&&CloseApplications||remote)&&!Critical.Contains(name))CloseProcess(process,visible);
                    } catch(ArgumentException){ } // Process exited during enumeration.
                      catch(InvalidOperationException){ }
                }
                if(Environment.TickCount64-scanStart>350)break;
            }
            if(RemoteEnforced&&Native.GetSystemMetrics(0x1000)!=0) {
                Emit(new{type="event",kind="remote_enforcement_failed",detail=new{reason="remote_session_detected"}});Release();
            }
            if(RemoteEnforced&&Environment.TickCount64-LastRemoteCheck>2000) {
                LastRemoteCheck=Environment.TickCount64;
                foreach(var name in RemoteServices) {
                    using var service=new ServiceController(name);
                    try {
                        if(service.Status==ServiceControllerStatus.Running) {
                            service.Stop();service.WaitForStatus(ServiceControllerStatus.Stopped,TimeSpan.FromSeconds(3));
                            Emit(new{type="event",kind="remote_control_blocked",detail=new{service=name,restarted_then_stopped=true}});
                        }
                    } catch(InvalidOperationException){ }
                    catch(Exception ex) {
                        RemoteEnforced=false;Emit(new{type="event",kind="remote_enforcement_failed",detail=new{service=name,error=ex.Message}});
                    }
                }
            }
          }
        } catch(Exception ex){LastError=ex.Message;} finally {Interlocked.Exchange(ref ApplicationBusy,0);}
    }
    static List<object> UnapprovedWindows() {
        var result=new List<object>();
        var windows=VisibleWindows();
        foreach(var process in Process.GetProcesses())using(process) {
            try {
                if(Trusted(process.Id)||process.SessionId!=OwnSession||Critical.Contains(process.ProcessName))continue;
                if(ApplicationWindows(process.Id,process.ProcessName,windows).Count==0)continue;
                result.Add(new{pid=process.Id,name=process.ProcessName+".exe"});
            } catch { }
        }
        return result;
    }
    static string WindowTitle(nint handle) {var text=new StringBuilder(512);Native.GetWindowText(handle,text,text.Capacity);return text.ToString();}
    // MainWindowHandle can be an invisible Explorer helper. Use the same actual
    // visible top-level windows for readiness and enforcement, including multiple folders.
    static bool ApplicationWindow(string processName,string cls,bool visible) {
        if(!visible || cls is "Shell_TrayWnd" or "Shell_SecondaryTrayWnd" or "Progman" or "WorkerW")return false;
        if(processName.Equals("explorer",StringComparison.OrdinalIgnoreCase))
            return cls is "CabinetWClass" or "ExploreWClass" or "#32770";
        return true;
    }
    static Dictionary<int,List<(nint handle,string cls)>> VisibleWindows() {
        var result=new Dictionary<int,List<(nint,string)>>();
        Native.EnumWindows((handle,_)=>{
            if(!Native.IsWindowVisible(handle))return true;
            Native.GetWindowThreadProcessId(handle,out var owner);
            var cls=new StringBuilder(256);Native.GetClassName(handle,cls,cls.Capacity);
            if(!result.TryGetValue((int)owner,out var list))result[(int)owner]=list=new();
            list.Add((handle,cls.ToString()));
            return true;
        },0);
        return result;
    }
    static List<nint> ApplicationWindows(int pid,string name,Dictionary<int,List<(nint handle,string cls)>>? windows=null) {
        windows??=VisibleWindows();
        return windows.TryGetValue(pid,out var list)?list.Where(x=>ApplicationWindow(name,x.cls,true)).Select(x=>x.handle).ToList():new();
    }
    static bool InputDesktopAvailable() {
        var desktop=Native.OpenInputDesktop(0,false,1);
        if(desktop==0)return false;
        try {var name=new StringBuilder(256);return Native.GetUserObjectInformation(desktop,2,name,512,out _)&&name.ToString().Equals("default",StringComparison.OrdinalIgnoreCase);}
        finally {Native.CloseDesktop(desktop);}
    }
    static string? ScreenImage() {
        try {
            var width=Native.GetSystemMetrics(0);var height=Native.GetSystemMetrics(1);
            using var full=new Bitmap(width,height);using(var graphics=Graphics.FromImage(full))graphics.CopyFromScreen(0,0,0,0,full.Size,CopyPixelOperation.SourceCopy);
            var scaledWidth=Math.Min(1280,width);using var scaled=new Bitmap(full,new Size(scaledWidth,Math.Max(1,height*scaledWidth/width)));
            using var buffer=new MemoryStream();scaled.Save(buffer,ImageFormat.Jpeg);return Convert.ToBase64String(buffer.ToArray());
        } catch{return null;}
    }
    static void CloseProcess(Process process,bool visible,bool capture=true) {
        var pid=process.Id;var name=process.ProcessName+".exe";var handle=process.MainWindowHandle;
        if(Trusted(pid))return;
        // A parent editor can own a kill-on-close Job containing the exam. Never
        // kill that parent: reject readiness and recover restrictions instead.
        // Explorer folder windows are handled below without terminating its process.
        if(ExamLauncher(pid)&&!process.ProcessName.Equals("explorer",StringComparison.OrdinalIgnoreCase)) {
            LastError="Қосымшаны жұмыс үстеліндегі Sergек таныстыру таңбашасымен қайта ашыңыз";
            Emit(new{type="event",kind="application_close_failed",detail=new{pid,name,blocked=false,reason="launcher_owns_exam"}});
            Release();return;
        }
        var title=WindowTitle(handle);
        // Close Explorer/UWP windows, never terminate the Windows shell or UWP host.
        if(process.ProcessName.Equals("explorer",StringComparison.OrdinalIgnoreCase)||process.ProcessName.Equals("ApplicationFrameHost",StringComparison.OrdinalIgnoreCase)) {
            foreach(var target in ApplicationWindows(pid,process.ProcessName)) {
                var picture=capture?ScreenImage():null;
                var windowTitle=WindowTitle(target);
                var closed=CloseApplicationWindow(target,pid);
                Emit(new{type="event",kind=closed?"application_closed":"application_close_failed",detail=new{pid,name,title=windowTitle,blocked=closed,screen_jpeg=picture}});
            }
            return;
        }
        var processPicture=visible&&capture?ScreenImage():null;
        try {
            if(visible)process.CloseMainWindow();
            if(!process.WaitForExit(120))process.Kill();
            bool closed=process.WaitForExit(700);
            Emit(new{type="event",kind=closed?"application_closed":"application_close_failed",detail=new{pid,name,title,blocked=closed,screen_jpeg=processPicture}});
        } catch(Exception ex) {
            Emit(new{type="event",kind="application_close_failed",detail=new{pid,name,title,blocked=false,error=ex.Message,screen_jpeg=processPicture}});
        }
    }
    static bool CloseApplicationWindow(nint handle,int pid) {
        if(!Native.IsWindow(handle)||!Native.IsWindowVisible(handle))return true;
        Native.GetWindowThreadProcessId(handle,out var owner);if(owner!=pid)return true;
        if(!Native.PostMessage(handle,0x10,0,0))return false;
        var deadline=Environment.TickCount64+1500;
        do {
            if(!Native.IsWindow(handle)||!Native.IsWindowVisible(handle))return true;
            Native.GetWindowThreadProcessId(handle,out owner);if(owner!=pid)return true;
            Thread.Sleep(25);
        } while(Environment.TickCount64<deadline);
        return false;
    }
    static void ApplyRemote() {
        if(Native.GetSystemMetrics(0x1000)!=0)throw new InvalidOperationException("Strict exam requires a local Windows session, not RDP.");
        if(!Admin())throw new InvalidOperationException("Remote control restriction requires administrator.");
        if(File.Exists(RemoteJournalPath))throw new IOException("Remote service recovery pending.");
        RemoteBackups=new();
        foreach(var name in RemoteServices) {
            using var service=new ServiceController(name);
            try {
                using var key=Registry.LocalMachine.OpenSubKey(@"SYSTEM\CurrentControlSet\Services\"+name,false);
                RemoteBackups.Add(new(name,service.Status==ServiceControllerStatus.Running,key?.GetValue("Start") is int start?start:3));
            }
            catch(InvalidOperationException) { }
        }
        File.WriteAllText(RemoteJournalPath,JsonSerializer.Serialize(RemoteBackups));
        foreach(var entry in RemoteBackups)SetServiceStart(entry.Name,4);
        foreach(var entry in RemoteBackups.Where(entry=>entry.Running)) {
            using var service=new ServiceController(entry.Name);service.Stop();service.WaitForStatus(ServiceControllerStatus.Stopped,TimeSpan.FromSeconds(2));
        }
        RemoteEnforced=true;
        Emit(new{type="event",kind="remote_control_blocked",detail=new{services_disabled=RemoteBackups.Select(entry=>entry.Name),remote_session=false}});
    }
    static void RecoverRemote() {
        if(!File.Exists(RemoteJournalPath))return;
        try {RemoteBackups=JsonSerializer.Deserialize<List<RemoteBackup>>(File.ReadAllText(RemoteJournalPath))??new();RestoreRemote();}
        catch(Exception ex){LastError="Remote recovery requires administrator: "+ex.Message;}
    }
    static void RestoreRemote() {
        RemoteEnforced=false;
        foreach(var entry in RemoteBackups.AsEnumerable().Reverse()) {
            if(!RemoteServices.Contains(entry.Name)||entry.Start<0||entry.Start>4)throw new IOException("Invalid remote recovery entry");
            SetServiceStart(entry.Name,entry.Start);
            using var service=new ServiceController(entry.Name);service.Refresh();
            if(entry.Running&&service.Status!=ServiceControllerStatus.Running) {
                if(entry.Start==4)SetServiceStart(entry.Name,3);
                service.Start();
                if(entry.Start==4)SetServiceStart(entry.Name,4);
            }
        }
        RemoteBackups.Clear();if(RemoteJournalPath.Length>0)File.Delete(RemoteJournalPath);
    }
    static void SetServiceStart(string name,int start) {
        var manager=Native.OpenSCManager(null,null,1);if(manager==0)throw new Win32Exception(Marshal.GetLastWin32Error());
        try {
            var service=Native.OpenService(manager,name,2);if(service==0)throw new Win32Exception(Marshal.GetLastWin32Error());
            try {if(!Native.ChangeServiceConfig(service,uint.MaxValue,(uint)start,uint.MaxValue,null,null,0,null,null,null,null))throw new Win32Exception(Marshal.GetLastWin32Error());}
            finally {Native.CloseServiceHandle(service);}
        } finally {Native.CloseServiceHandle(manager);}
    }
}
internal static partial class Native {
    internal delegate bool WindowEnumerator(nint handle,nint parameter);
    [DllImport("user32.dll")]internal static extern bool EnumWindows(WindowEnumerator callback,nint parameter);
    [DllImport("user32.dll")]internal static extern bool IsWindowVisible(nint handle);
    [StructLayout(LayoutKind.Sequential,CharSet=CharSet.Unicode)]internal struct ProcessEntry {
        public uint size,usage,pid;public nuint heap;public uint module,threads,parent;public int priority;public uint flags;
        [MarshalAs(UnmanagedType.ByValTStr,SizeConst=260)]public string name;
    }
    [DllImport("kernel32.dll")]internal static extern nint CreateToolhelp32Snapshot(uint flags,uint pid);
    [DllImport("kernel32.dll",CharSet=CharSet.Unicode)]internal static extern bool Process32First(nint snapshot,ref ProcessEntry row);
    [DllImport("kernel32.dll",CharSet=CharSet.Unicode)]internal static extern bool Process32Next(nint snapshot,ref ProcessEntry row);
    [DllImport("kernel32.dll")]internal static extern bool CloseHandle(nint handle);
    [DllImport("user32.dll")]internal static extern nint GetForegroundWindow();
    [DllImport("user32.dll")]internal static extern uint GetWindowThreadProcessId(nint handle,out uint pid);
    [DllImport("user32.dll",CharSet=CharSet.Unicode)]internal static extern int GetWindowText(nint handle,StringBuilder text,int count);
    [DllImport("user32.dll",CharSet=CharSet.Unicode)]internal static extern int GetClassName(nint handle,StringBuilder text,int count);
    [DllImport("user32.dll")]internal static extern bool PostMessage(nint handle,uint message,nuint w,nint l);
    [DllImport("user32.dll")]internal static extern bool IsWindow(nint handle);
    [DllImport("user32.dll")]internal static extern int GetSystemMetrics(int index);
    [DllImport("user32.dll",SetLastError=true)]internal static extern nint OpenInputDesktop(uint flags,bool inherit,uint access);
    [DllImport("user32.dll",CharSet=CharSet.Unicode,SetLastError=true)]internal static extern bool GetUserObjectInformation(nint handle,int index,StringBuilder name,uint length,out uint needed);
    [DllImport("user32.dll")]internal static extern bool CloseDesktop(nint handle);
    [DllImport("advapi32.dll",CharSet=CharSet.Unicode,SetLastError=true)]internal static extern nint OpenSCManager(string? machine,string? database,uint access);
    [DllImport("advapi32.dll",CharSet=CharSet.Unicode,SetLastError=true)]internal static extern nint OpenService(nint manager,string name,uint access);
    [DllImport("advapi32.dll",CharSet=CharSet.Unicode,SetLastError=true)]internal static extern bool ChangeServiceConfig(nint service,uint type,uint start,uint error,string? binary,string? group,nint tag,string? dependencies,string? account,string? password,string? displayName);
    [DllImport("advapi32.dll")]internal static extern bool CloseServiceHandle(nint handle);
}
