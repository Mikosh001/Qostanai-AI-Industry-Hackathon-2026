using System.Runtime.InteropServices;
using System.Text.Json;
using Microsoft.Win32;

// Precision touchpad gestures are handled by the shell, not by WH_KEYBOARD_LL.
// The registry alone is insufficient: Explorer caches these four settings.
// Isolate the version-sensitive shell adapter, check its layout against the
// user's registry before writing, and verify the live cache after every change.
internal interface IGestureSettings {
    int? Read(string name);
    void Write(string name, int? value);
    int ReadLive(int id);
    void Refresh(int id);
}

internal sealed class GestureRestriction {
    internal record SavedSetting(int? Registry,int Live);
    internal static readonly (string Name,int Id,int Default)[] Settings = {
        ("ThreeFingerTapEnabled", 0x0F, 1), ("FourFingerTapEnabled", 0x10, 2),
        ("ThreeFingerSlideEnabled", 0x11, 1), ("FourFingerSlideEnabled", 0x12, 2)
    };
    readonly IGestureSettings store;
    readonly string journal;
    Dictionary<string,SavedSetting>? backup;
    internal bool Active { get; private set; }
    internal GestureRestriction(IGestureSettings store,string journal) {
        this.store=store;this.journal=journal;
    }
    internal bool IsBlocked() => Settings.All(s=>store.Read(s.Name)==0 && store.ReadLive(s.Id)==0);
    internal void Apply() {
        if(Active) { Ensure();return; }
        if(File.Exists(journal))throw new IOException("Touchpad settings recovery is pending.");
        // Do not write a setting through an unknown shell ABI/layout.
        foreach(var s in Settings) {
            var saved=store.Read(s.Name);
            var live=store.ReadLive(s.Id);
            if(saved.HasValue && saved.Value!=live)
                throw new IOException("Touchpad live settings do not match Windows settings: "+s.Name);
            if(live<0 || live>10)throw new IOException("Unsupported Windows touchpad settings layout.");
        }
        backup=Settings.ToDictionary(s=>s.Name,s=>new SavedSetting(store.Read(s.Name),store.ReadLive(s.Id)));
        // Persist and flush the recovery record BEFORE changing user settings.
        using(var file=new FileStream(journal,FileMode.CreateNew,FileAccess.Write,FileShare.None)) {
            JsonSerializer.Serialize(file,backup);file.Flush(true);
        }
        try { SetBlocked();Active=true; }
        catch { Restore();throw; }
    }
    void SetBlocked() {
        foreach(var s in Settings)store.Write(s.Name,0);
        foreach(var s in Settings)store.Refresh(s.Id);
        if(!WaitFor(IsBlocked))throw new IOException("Windows did not apply touchpad gesture protection: "+string.Join(", ",Settings.Select(s=>$"{s.Name}={store.Read(s.Name)}/{store.ReadLive(s.Id)}")));
    }
    static bool WaitFor(Func<bool> condition) {
        var deadline=Environment.TickCount64+1500;
        do {if(condition())return true;Thread.Sleep(20);}while(Environment.TickCount64<deadline);
        return condition();
    }
    internal bool Ensure() {
        if(!Active)throw new IOException("Touchpad gesture protection is inactive.");
        if(IsBlocked())return false;
        SetBlocked();return true;
    }
    internal void Restore() {
        Active=false;
        if(backup==null) {
            if(!File.Exists(journal))return;
            backup=JsonSerializer.Deserialize<Dictionary<string,SavedSetting>>(File.ReadAllText(journal))
                ??throw new IOException("Invalid touchpad recovery record.");
        }
        if(backup.Count!=Settings.Length || Settings.Any(s=>!backup.ContainsKey(s.Name) || backup[s.Name]==null || backup[s.Name].Live<0 || backup[s.Name].Live>10 || backup[s.Name].Registry is <0 or >10))
            throw new IOException("Invalid touchpad recovery settings.");
        foreach(var s in Settings)store.Write(s.Name,backup[s.Name].Registry);
        foreach(var s in Settings)store.Refresh(s.Id);
        if(!WaitFor(()=>Settings.All(s=>store.Read(s.Name)==backup[s.Name].Registry && store.ReadLive(s.Id)==backup[s.Name].Live)))
            throw new IOException("Touchpad settings recovery was not confirmed.");
        File.Delete(journal);backup=null;
    }
}

internal sealed class WindowsGestureSettings : IGestureSettings, IDisposable {
    internal const string RegistryPath=@"Software\Microsoft\Windows\CurrentVersion\PrecisionTouchPad";
    object? shell;
    IImmersiveSettingsCache? cache;
    readonly int idOffset;
    internal WindowsGestureSettings() {
        // This shell interface is not a public Windows API. Reject unsupported
        // versions rather than treating a registry-only write as protection.
        if(!OperatingSystem.IsWindowsVersionAtLeast(10,0,19041))
            throw new PlatformNotSupportedException("Windows 10 2004 or later is required for touchpad protection.");
        var build=Environment.OSVersion.Version.Build;
        idOffset=build<22000?-6:build<22621?-1:0;
        try {
            var clsid=new Guid("c2f03a33-21f5-47fa-b4bb-156362a2f239");
            var provider=typeof(IShellServices).GUID;
            // Explicitly connect to the shell's out-of-process service. The
            // caller must also be outside packaged-editor registry virtualization.
            Marshal.ThrowExceptionForHR(CoCreateInstance(ref clsid,0,4,ref provider,out var server));
            shell=server;
            var sid=new Guid("53660488-8855-460b-a9ab-5cfc6b5012ca");
            var iid=typeof(IImmersiveSettingsCache).GUID;
            Marshal.ThrowExceptionForHR(((IShellServices)shell).QueryService(ref sid,ref iid,out var service));
            cache=(IImmersiveSettingsCache)service;
        } catch { Dispose();throw; }
    }
    public int? Read(string name) {
        using var key=Registry.CurrentUser.OpenSubKey(RegistryPath);
        var value=key?.GetValue(name);
        if(value==null)return null;
        if(value is not int integer || key!.GetValueKind(name)!=RegistryValueKind.DWord)
            throw new IOException("Unexpected Windows touchpad setting type: "+name);
        return integer;
    }
    public void Write(string name,int? value) {
        using var key=Registry.CurrentUser.CreateSubKey(RegistryPath,true);
        if(value.HasValue)key.SetValue(name,value.Value,RegistryValueKind.DWord);
        else key.DeleteValue(name,false);
        key.Flush();
    }
    public int ReadLive(int id) {
        Marshal.ThrowExceptionForHR(cache!.GetDWORD(id+idOffset,out var value));return checked((int)value);
    }
    public void Refresh(int id)=>Marshal.ThrowExceptionForHR(cache!.OnSettingChanged(id+idOffset));
    public void Dispose() {
        if(cache!=null) {Marshal.ReleaseComObject(cache);cache=null;}
        if(shell!=null) {Marshal.ReleaseComObject(shell);shell=null;}
    }
    [DllImport("ole32.dll",ExactSpelling=true)]
    static extern int CoCreateInstance(ref Guid clsid,nint outer,uint context,ref Guid iid,[MarshalAs(UnmanagedType.Interface)]out object result);
    [ComImport,Guid("6d5140c1-7436-11ce-8034-00aa006009fa"),InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
    interface IShellServices {
        [PreserveSig]int QueryService(ref Guid service,ref Guid iid,[MarshalAs(UnmanagedType.Interface)]out object result);
    }
    [ComImport,Guid("4214f6fa-eb36-4e2f-9ca2-23fdc1832df7"),InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
    interface IImmersiveSettingsCache {
        [PreserveSig]int OnSettingChanged(int id);
        [PreserveSig]int GetBOOL(int id,[MarshalAs(UnmanagedType.Bool)]out bool value);
        [PreserveSig]int GetDWORD(int id,out uint value);
        [PreserveSig]int RegisterForSettingChange(nint callback,out uint cookie);
        [PreserveSig]int UnregisterForSettingChange(uint cookie);
    }
}

internal static partial class Program {
    static GestureRestriction? Gestures;
    static WindowsGestureSettings? GestureStore;
    static string GestureJournalPath="";
    static string GestureLeasePath="";
    static FileStream? GestureLease;
    static long LastGestureCheck;
    static void ApplyGestures() {
        GestureStore??=new WindowsGestureSettings();
        Gestures??=new GestureRestriction(GestureStore,GestureJournalPath);
        AcquireGestureLease();
        Gestures.Apply();
    }
    static void AcquireGestureLease() {
        if(GestureLease==null && GestureLeasePath.Length>0)
            GestureLease=new FileStream(GestureLeasePath,FileMode.OpenOrCreate,FileAccess.ReadWrite,FileShare.None);
    }
    static void RestoreGestures() {
        if(Gestures==null && !File.Exists(GestureJournalPath))return;
        AcquireGestureLease();
        if(Gestures==null && File.Exists(GestureJournalPath)) {
            GestureStore??=new WindowsGestureSettings();
            Gestures=new GestureRestriction(GestureStore,GestureJournalPath);
        }
        Gestures?.Restore();
        GestureLease?.Dispose();GestureLease=null;
    }
    static void VerifyGestures() {
        if(!Active || !BlockKeyboard || Environment.TickCount64-LastGestureCheck<500)return;
        LastGestureCheck=Environment.TickCount64;
        try {
            if(Gestures==null)throw new IOException("Touchpad protection unavailable.");
            if(Gestures.Ensure())Emit(new{type="event",kind="gesture_settings_restored",detail=new{blocked=true}});
        } catch(Exception ex) {
            LastError=ex.Message;
            Emit(new{type="event",kind="gesture_enforcement_failed",detail=new{reason="touchpad_protection_lost",error=ex.Message}});
            Release();
        }
    }
    static bool ProbeGestures() {
        try {
            using var store=new WindowsGestureSettings();
            var settings=GestureRestriction.Settings.Select(s=>new{name=s.Name,registry=store.Read(s.Name),live=store.ReadLive(s.Id)}).ToArray();
            var passed=settings.All(s=>s.registry==null || s.registry==s.live);
            Emit(new{type="gesture_probe",passed,windows_build=Environment.OSVersion.Version.Build,settings,changes=false});
            return passed;
        } catch(Exception ex) {Emit(new{type="gesture_probe",passed=false,error=ex.Message,changes=false});return false;}
    }
}
