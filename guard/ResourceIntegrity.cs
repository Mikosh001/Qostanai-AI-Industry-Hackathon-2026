using System.Security.Cryptography;
using System.Text.Json;

internal sealed class ResourceIntegrity : IDisposable {
    internal record Entry(string path,long size,string sha256);
    readonly string root;
    readonly object sync=new();
    readonly List<FileStream> locks=new();
    HashSet<string> expected=new(StringComparer.OrdinalIgnoreCase);
    int ready;
    internal bool Ready {get=>Volatile.Read(ref ready)!=0;private set=>Volatile.Write(ref ready,value?1:0);}
    internal string? Error {get;private set;}
    internal int Count=>expected.Count;
    internal long DurationMs {get;private set;}
    internal ResourceIntegrity(string root){this.root=Path.GetFullPath(root);}
    internal void Verify(Entry[] entries,bool lockAsar=true) {
        lock(sync) {
        var watch=System.Diagnostics.Stopwatch.StartNew();
        try {
            if(entries.Length==0||entries.Length>10000)throw new IOException("Invalid resource inventory");
            foreach(var entry in entries) {
                if(entry.path.Contains('\\')||entry.path.Contains(':')||entry.path.Split('/').Any(p=>p is "" or "." or "..")||!new[]{"backend/","guard/","models/","ui/"}.Any(p=>entry.path.StartsWith(p,StringComparison.Ordinal))||entry.size<0||entry.sha256.Length!=64||!entry.sha256.All(Uri.IsHexDigit)||!expected.Add(entry.path))
                    throw new IOException("Invalid resource entry");
            }
            CheckInventory();
            if(lockAsar)locks.Add(new FileStream(Path.Combine(root,"app.asar"),FileMode.Open,FileAccess.Read,FileShare.Read));
            foreach(var entry in entries) {
                var stream=new FileStream(Path.Combine(root,entry.path.Replace('/',Path.DirectorySeparatorChar)),FileMode.Open,FileAccess.Read,FileShare.Read);
                locks.Add(stream);
                if(stream.Length!=entry.size||!Convert.ToHexString(SHA256.HashData(stream)).Equals(entry.sha256,StringComparison.OrdinalIgnoreCase))throw new IOException("Resource digest mismatch: "+entry.path);
            }
            CheckInventory();Ready=true;
        }catch(Exception ex){Error=ex.Message;Dispose();throw;}
        finally{DurationMs=watch.ElapsedMilliseconds;}
        }
    }
    IEnumerable<string> Inventory(string folder) {
        if((File.GetAttributes(folder)&FileAttributes.ReparsePoint)!=0)throw new IOException("Linked resource directory");
        foreach(var file in Directory.EnumerateFileSystemEntries(folder)) {
            var attrs=File.GetAttributes(file);
            if((attrs&FileAttributes.ReparsePoint)!=0)throw new IOException("Linked resource path");
            if((attrs&FileAttributes.Directory)!=0)foreach(var child in Inventory(file))yield return child;
            else yield return Path.GetRelativePath(root,file).Replace('\\','/');
        }
    }
    internal void CheckInventory() {
        lock(sync) {
        try {
            var actual=new HashSet<string>(StringComparer.OrdinalIgnoreCase);
            foreach(var name in new[]{"backend","guard","models","ui"})foreach(var file in Inventory(Path.Combine(root,name)))actual.Add(file);
            if(!actual.SetEquals(expected))throw new IOException("Resource inventory changed");
        }catch{Ready=false;Error="package_inventory_changed";throw;}
        }
    }
    public void Dispose(){lock(sync){Ready=false;foreach(var stream in locks)stream.Dispose();locks.Clear();}}
}
internal static partial class Program {
    static ResourceIntegrity? Resources;
    static int IntegrityBusy;
    static void QueueResourceVerification(JsonElement root) {
        if(Active||Resources!=null)throw new IOException("Resource verification already initialized");
        var entries=root.GetProperty("entries").Deserialize<ResourceIntegrity.Entry[]>()??throw new IOException("Resource manifest missing");
        Resources=new ResourceIntegrity(Path.GetFullPath(Path.Combine(AppContext.BaseDirectory,"..")));
        Interlocked.Exchange(ref IntegrityBusy,1);
        _=Task.Run(()=>{try{Resources.Verify(entries);}catch{}finally{Interlocked.Exchange(ref IntegrityBusy,0);}});
    }
    static object ResourceStatus(){var pending=Volatile.Read(ref IntegrityBusy)!=0;return new{ready=Resources?.Ready==true,pending,files=Resources?.Count??0,duration_ms=Resources?.DurationMs??0,error=Resources?.Error};}
}
