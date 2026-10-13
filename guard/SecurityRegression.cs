using System.Security.Cryptography;

internal static partial class Program {
    static bool SecurityRegression() {
        var checks=new List<string>();string? error=null;
        void Check(bool ok,string name){if(!ok)throw new Exception(name);checks.Add(name);}
        bool Fails(Action action){try{action();return false;}catch(IOException){return true;}}
        var folder=Path.Combine(Path.GetTempPath(),"sergek-security-"+Guid.NewGuid().ToString("N"));
        Directory.CreateDirectory(folder);
        try {
            var good=new AntimalwareHealth(true,true,true,true,true,true,true,0,0);
            Check(good.Ready,"healthy Defender state accepted");
            foreach(var bad in new[]{good with{Available=false},good with{Antivirus=false},good with{Realtime=false},good with{Behavior=false},good with{OnAccess=false},good with{Ioav=false},good with{Tamper=false},good with{Tamper=null},good with{SignatureAge=-1},good with{SignatureAge=8},good with{ActiveThreats=-1},good with{ActiveThreats=1}})
                Check(!bad.Ready,"unready antivirus state "+checks.Count);
            Check((good with{SignatureAge=7}).Ready,"signature age boundary accepted");
            AntivirusHealth=good;AntivirusCheckedTick=Environment.TickCount64-46000;AntivirusRequired=true;Active=true;Lease=Environment.TickCount64;
            CheckLease();Check(!Active,"stale security status releases exam even if WMI is stalled");
            AntivirusHealth=good with{Realtime=false};AntivirusCheckedTick=Environment.TickCount64;AntivirusRequired=true;Active=true;Lease=Environment.TickCount64;
            CheckLease();Check(!Active,"known disabled protection is stopped by the independent watchdog");
            foreach(var name in new[]{"backend","guard","models","ui"})Directory.CreateDirectory(Path.Combine(folder,name));
            var entries=new List<ResourceIntegrity.Entry>();
            foreach(var name in new[]{"backend/fixture.dll","guard/fixture.dll","models/fixture.onnx","ui/index.html"}) {
                var file=Path.Combine(folder,name);File.WriteAllText(file,"harmless isolated fixture "+name);
                var bytes=File.ReadAllBytes(file);entries.Add(new(name,bytes.Length,Convert.ToHexString(SHA256.HashData(bytes))));
            }
            var target=Path.Combine(folder,"models/fixture.onnx");
            using(var resources=new ResourceIntegrity(folder)) {
                resources.Verify(entries.ToArray(),false);Check(resources.Ready&&resources.Count==4,"all resource digests verified");
                Check(Fails(()=>File.WriteAllText(target,"changed")),"Windows denies writes while file is held");
                Check(Fails(()=>File.Delete(target)),"Windows denies replacement/delete while file is held");
                Check(File.ReadAllText(target).StartsWith("harmless"),"readers and model loading remain available");
                File.WriteAllText(Path.Combine(folder,"guard/extra.dll"),"harmless added fixture");
                Check(Fails(resources.CheckInventory)&&!resources.Ready,"unexpected resource executable invalidates inventory");
                File.Delete(Path.Combine(folder,"guard/extra.dll"));
            }
            File.WriteAllText(target,"modified fixture");
            using(var resources=new ResourceIntegrity(folder))Check(Fails(()=>resources.Verify(entries.ToArray(),false)),"changed model digest rejected");
            Check(Fails(()=>new ResourceIntegrity(folder).Verify(Array.Empty<ResourceIntegrity.Entry>(),false)),"empty manifest rejected");
            Check(Fails(()=>new ResourceIntegrity(folder).Verify(new[]{new ResourceIntegrity.Entry("../outside.dll",1,new string('0',64))},false)),"traversal rejected before file access");
            Check(Fails(()=>new ResourceIntegrity(folder).Verify(new[]{entries[0],entries[0]},false)),"duplicate resource entries rejected");
            // A failed verification must not leave earlier files locked.
            File.WriteAllText(Path.Combine(folder,"backend/fixture.dll"),"writable after failed verification");
            Check(true,"failed verification releases file handles");
        }catch(Exception ex){error=ex.Message;}
        finally{Active=false;AntivirusRequired=false;}
        Emit(new{type="security_regression",passed=error==null,checks=checks.Count,cases=checks,error,scope="synthetic antivirus states and own temporary resource files; no malware and no Windows protection settings modified"});
        return error==null;
    }
}
