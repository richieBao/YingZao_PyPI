using System;
using System.Drawing;
using Grasshopper.Kernel;

namespace YingZao.GH;

public sealed class YingZaoGhInfo : GH_AssemblyInfo
{
    public override string Name => "YingZao.GH";

    public override Bitmap Icon => null;

    public override string Description =>
        "Stable Grasshopper components for the YingZao toolkit.";

    public override Guid Id => new Guid("48741B76-6386-4429-9AAB-6E5F8F327C6E");

    public override string AuthorName => "Richie Bao";

    public override string AuthorContact => "https://coding-x.tech/";
}
