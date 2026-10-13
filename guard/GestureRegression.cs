using System.Text.Json;

internal static partial class Program {
    sealed class FakeGestureSettings : IGestureSettings {
        internal Dictionary<string,int?> Values=GestureRestriction.Settings.ToDictionary(s=>s.Name,s=>(int?)s.Default);
        internal Dictionary<int,int> Live=GestureRestriction.Settings.ToDictionary(s=>s.Id,s=>s.Default);
        internal bool IgnoreBlocked,FailRefresh;
        internal int Writes;
        public int? Read(string name)=>Values[name];
        public void Write(string name,int? value){Values[name]=value;Writes++;}
        public int ReadLive(int id)=>Live[id];
        public void Refresh(int id) {
            if(FailRefresh)throw new IOException("fixture cache unavailable");
            var s=GestureRestriction.Settings.Single(s=>s.Id==id);
            if(!(IgnoreBlocked && Values[s.Name]==0))Live[id]=Values[s.Name]??s.Default;
        }
    }
    static bool GestureRegression() {
        var folder=Path.Combine(Path.GetTempPath(),"sergek-gesture-tests-"+Guid.NewGuid().ToString("N"));
        Directory.CreateDirectory(folder);
        var cases=new List<string>();string? error=null;
        void Check(bool condition,string name){if(!condition)throw new Exception(name);cases.Add(name);}
        bool Throws(Action action){try{action();return false;}catch(IOException){return true;}}
        try {
            var fake=new FakeGestureSettings();var journal=Path.Combine(folder,"normal.json");
            var saved=JsonSerializer.Serialize(fake.Values);
            var guard=new GestureRestriction(fake,journal);
            guard.Apply();Check(guard.Active&&guard.IsBlocked()&&File.Exists(journal),"live cache and registry blocked after durable backup");
            Check(!guard.Ensure(),"unchanged policy does not rewrite");
            guard.Apply();Check(guard.IsBlocked(),"repeated activation idempotent");
            fake.Values["FourFingerSlideEnabled"]=2;fake.Live[0x12]=2;
            Check(guard.Ensure()&&guard.IsBlocked(),"tampered gestures reblocked");
            guard.Restore();Check(!guard.Active&&!File.Exists(journal)&&JsonSerializer.Serialize(fake.Values)==saved,"original settings restored");
            guard.Restore();Check(!File.Exists(journal),"release idempotent");

            fake.Values["ThreeFingerTapEnabled"]=null;fake.Live[0x0F]=1;
            var missing=new GestureRestriction(fake,Path.Combine(folder,"absent.json"));missing.Apply();missing.Restore();
            Check(fake.Values["ThreeFingerTapEnabled"]==null&&fake.Live[0x0F]==1,"absent registry value stays absent");

            var crashJournal=Path.Combine(folder,"crash.json");
            new GestureRestriction(fake,crashJournal).Apply();
            Check(Throws(()=>new GestureRestriction(fake,crashJournal).Apply()),"existing recovery record is never overwritten");
            new GestureRestriction(fake,crashJournal).Restore();
            Check(!File.Exists(crashJournal)&&fake.Values["FourFingerSlideEnabled"]==2,"new process restores saved settings after crash");

            fake=new FakeGestureSettings{IgnoreBlocked=true};journal=Path.Combine(folder,"failure.json");
            Check(Throws(()=>new GestureRestriction(fake,journal).Apply())&&!File.Exists(journal)&&fake.Values["FourFingerSlideEnabled"]==2,"registry alone cannot pass and rollback restores values");

            fake=new FakeGestureSettings();fake.Live[0x12]=1;
            Check(Throws(()=>new GestureRestriction(fake,Path.Combine(folder,"layout.json")).Apply())&&fake.Writes==0,"unknown cache layout rejected before mutation");

            fake=new FakeGestureSettings();journal=Path.Combine(folder,"retry.json");guard=new GestureRestriction(fake,journal);guard.Apply();
            fake.FailRefresh=true;Check(Throws(guard.Restore)&&File.Exists(journal),"failed restoration retains durable recovery record");
            fake.FailRefresh=false;guard.Restore();Check(!File.Exists(journal)&&fake.Live[0x12]==2,"restoration can be retried");
            journal=Path.Combine(folder,"invalid.json");File.WriteAllText(journal,"{}");
            var writes=fake.Writes;
            Check(Throws(()=>new GestureRestriction(fake,journal).Restore())&&fake.Writes==writes,"invalid journal rejected without setting writes");
        } catch(Exception ex){error=ex.Message;}
        Emit(new{type="gesture_regression",passed=error==null,checks=cases.Count,cases,scope="in-memory settings and isolated temporary files; no Windows settings changed",error});
        return error==null;
    }
    static bool LiveGestureRegression() {
        var folder=Path.Combine(Path.GetTempPath(),"sergek-gesture-live-"+Guid.NewGuid().ToString("N"));Directory.CreateDirectory(folder);
        string? error=null;bool blocked=false,restored=false,leaseRestored=false;Dictionary<string,object>? before=null,after=null,during=null;
        using var store=new WindowsGestureSettings();
        Dictionary<string,object> Snapshot()=>GestureRestriction.Settings.ToDictionary(s=>s.Name,s=>(object)new{registry=store.Read(s.Name),live=store.ReadLive(s.Id)});
        var guard=new GestureRestriction(store,Path.Combine(folder,"gesture-recovery.json"));
        try {
            before=Snapshot();guard.Apply();during=Snapshot();blocked=guard.IsBlocked();
            guard.Restore();
            // Exercise the actual guard's emergency/lease Release path too,
            // without installing a keyboard hook or applying other restrictions.
            GestureStore=store;Gestures=guard;guard.Apply();BlockKeyboard=true;Active=true;
            Lease=Environment.TickCount64-10001;CheckLease();
            leaseRestored=!Active&&!guard.Active&&JsonSerializer.Serialize(before)==JsonSerializer.Serialize(Snapshot());
        }
        catch(Exception ex){error=ex.Message;}
        finally {
            try{guard.Restore();after=Snapshot();restored=JsonSerializer.Serialize(before)==JsonSerializer.Serialize(after);}
            catch(Exception ex){error="Recovery: "+ex.Message;}
        }
        var passed=blocked&&restored&&leaseRestored&&error==null;
        Emit(new{type="gesture_live_regression",passed,blocked,restored,lease_restored=leaseRestored,windows_build=Environment.OSVersion.Version.Build,before,during,after,error,scope="temporarily disables only three/four-finger shell gestures, then restores them; no other apps closed; no keyboard hook, USB or remote restrictions"});
        return passed;
    }
}
