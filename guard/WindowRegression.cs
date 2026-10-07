using System.Runtime.InteropServices;

internal static partial class Program {
    static bool LauncherRegression() {
        var previousParents=Parents;var previousTrusted=TrustedPids;var previousOwner=ExamOwnerPid;
        try {
            Parents=new(){{102,101},{101,100},{103,102},{200,100}};
            TrustedPids=new(){102};ExamOwnerPid=102;
            return Trusted(102)&&Trusted(103)&&!Trusted(101)&&ExamLauncher(101)&&ExamLauncher(100)&&!ExamLauncher(102)&&!ExamLauncher(200);
        } finally {Parents=previousParents;TrustedPids=previousTrusted;ExamOwnerPid=previousOwner;}
    }
    // Creates and closes ONLY this test process's windows. No restrictions,
    // registry, services, keyboard hook, or other applications are touched.
    static bool WindowRegression() {
        var checks=new[]{
            !ApplicationWindow("explorer","Shell_TrayWnd",true),
            !ApplicationWindow("explorer","Shell_SecondaryTrayWnd",true),
            !ApplicationWindow("explorer","Progman",true),
            !ApplicationWindow("explorer","WorkerW",true),
            !ApplicationWindow("explorer","tooltips_class32",true),
            !ApplicationWindow("explorer","CabinetWClass",false),
            ApplicationWindow("explorer","CabinetWClass",true),
            ApplicationWindow("explorer","ExploreWClass",true),
            ApplicationWindow("explorer","#32770",true),
            ApplicationWindow("other","Chrome_WidgetWin_1",true)
        };
        using var ready=new ManualResetEventSlim();
        var handles=new List<nint>();string? error=null;
        uint threadId=0;
        Native.TestWindowProc callback=(handle,message,w,l)=>{
            // Explorer can take longer than the old 100 ms acknowledgement limit.
            if(message==0x10)Thread.Sleep(250);
            return Native.DefWindowProc(handle,message,w,l);
        };
        var thread=new Thread(()=>{
            threadId=Native.GetCurrentThreadId();
            try {
                foreach(var cls in new[]{"CabinetWClass","WorkerW","SergekHiddenHelper"}) {
                    var type=new Native.TestWindowClass{size=(uint)Marshal.SizeOf<Native.TestWindowClass>(),callback=callback,instance=Native.GetModuleHandle(null),className=cls};
                    if(Native.RegisterClassEx(ref type)==0)throw new Exception("fixture class registration failed");
                }
                foreach(var cls in new[]{"CabinetWClass","CabinetWClass","WorkerW","SergekHiddenHelper"}) {
                    var visible=cls!="SergekHiddenHelper";
                    var handle=Native.CreateWindowEx(0,cls,"",visible?0x90000000u:0x80000000u,-32000,-32000,10,10,0,0,Native.GetModuleHandle(null),0);
                    if(handle==0)throw new Exception("fixture window creation failed");
                    handles.Add(handle);
                }
                ready.Set();
                while(Native.GetMessage(out var message,0,0,0)>0){Native.TranslateMessage(ref message);Native.DispatchMessage(ref message);}
            } catch(Exception ex){error=ex.Message;ready.Set();}
            finally {foreach(var handle in handles)if(Native.IsWindow(handle))Native.DestroyWindow(handle);}
        }){IsBackground=true};thread.Start();
        bool passed=false;
        try {
            if(!ready.Wait(3000)||error!=null)throw new Exception(error??"fixture timeout");
            var windows=ApplicationWindows(Environment.ProcessId,"explorer");
            passed=checks.All(x=>x)&&windows.Count==2;
            foreach(var handle in windows)passed=CloseApplicationWindow(handle,Environment.ProcessId)&&passed;
            passed=passed&&ApplicationWindows(Environment.ProcessId,"explorer").Count==0&&Native.IsWindow(handles[2])&&Native.IsWindow(handles[3]);
        } catch(Exception ex){error=ex.Message;}
        finally {Native.PostThreadMessage(threadId,0x12,0,0);thread.Join(3000);GC.KeepAlive(callback);}
        Emit(new{type="window_regression",passed,checks=checks.Length,closed_folder_windows=2,shell_preserved=true,hidden_helper_preserved=true,scope="own process windows only",error});
        return passed;
    }
}
internal static partial class Native {
    internal delegate nint TestWindowProc(nint handle,uint message,nuint w,nint l);
    [StructLayout(LayoutKind.Sequential,CharSet=CharSet.Unicode)]internal struct TestWindowClass {
        public uint size,style;public TestWindowProc callback;public int classExtra,windowExtra;
        public nint instance,icon,cursor,background;public string? menuName;public string className;public nint smallIcon;
    }
    [DllImport("user32.dll",CharSet=CharSet.Unicode)]internal static extern ushort RegisterClassEx(ref TestWindowClass value);
    [DllImport("user32.dll",CharSet=CharSet.Unicode)]internal static extern nint CreateWindowEx(uint extra,string cls,string title,uint style,int x,int y,int width,int height,nint parent,nint menu,nint instance,nint param);
    [DllImport("user32.dll",CharSet=CharSet.Unicode)]internal static extern nint DefWindowProc(nint handle,uint message,nuint w,nint l);
    [DllImport("user32.dll")]internal static extern bool DestroyWindow(nint handle);
}
