using Grasshopper.Kernel;

namespace YingZao.GH;

internal sealed class SchemaField
{
    public SchemaField(string name, GH_ParamAccess access)
    {
        Name = name;
        Access = access;
    }

    public string Name { get; }

    public GH_ParamAccess Access { get; }
}
