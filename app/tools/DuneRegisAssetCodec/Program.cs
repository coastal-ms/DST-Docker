using UAssetAPI;
using UAssetAPI.UnrealTypes;

// The same UAssetAPI revision used by UAssetGUI 1.1.0, without Windows Forms.
// Only the two fixed, locally extracted Tank assets are passed by the job.
try
{
    if (args.Length != 3 || args[0] is not ("tojson" or "fromjson"))
        throw new ArgumentException("Choose tojson or fromjson, input and new output.");
    var input = Path.GetFullPath(args[1]);
    var output = Path.GetFullPath(args[2]);
    if (input == output || File.Exists(output)) throw new IOException("Output must be a new file.");
    if (args[0] == "tojson")
    {
        var asset = new UAsset(input, EngineVersion.VER_UE5_2);
        File.WriteAllText(output, asset.SerializeJson(Newtonsoft.Json.Formatting.Indented));
    }
    else
    {
        using var stream = File.OpenRead(input);
        var asset = UAsset.DeserializeJson(stream) ?? throw new IOException("Invalid asset JSON.");
        asset.FilePath = input;
        asset.Write(output);
    }
    return 0;
}
catch (Exception error)
{
    Console.Error.WriteLine(error.Message);
    return 1;
}
