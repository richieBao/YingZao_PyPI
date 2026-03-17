#nullable enable

using System;
using System.Collections;
using System.Collections.Generic;
using System.Drawing;
using System.Drawing.Drawing2D;
using System.Linq;
using System.Reflection;
using System.Text;
using GH_IO.Serialization;
using Grasshopper.Kernel;
using Grasshopper.Kernel.Data;
using Grasshopper.Kernel.Parameters;
using Grasshopper.Kernel.Types;

namespace YingZao.GH.Components;

public sealed class DbFieldsToOutputsComponent : GH_Component, IGH_VariableParameterComponent
{
    private readonly List<SchemaField> _schema = new();
    private List<SchemaField>? _pendingSchema;

    public DbFieldsToOutputsComponent()
        : base(
            "DB Fields To Outputs",
            "DbFields",
            "Expand database fields into stable variable Grasshopper outputs.",
            "YingZaoLab",
            "輔助工具")
    {
    }

    public override Guid ComponentGuid => new("A19C2AE5-5511-4B49-AF4E-8A83349623DA");

    protected override Bitmap Icon => DbFieldsToOutputsIcon.Create();

    protected override void RegisterInputParams(GH_InputParamManager pManager)
    {
        pManager.AddGenericParameter("All", "All", "Ordered field/value pairs from the Python core.", GH_ParamAccess.list);
        pManager.AddBooleanParameter(
            "RefreshOutputs",
            "Refresh",
            "Apply the current input schema to dynamic outputs on the next solution.",
            GH_ParamAccess.item,
            false);
    }

    protected override void RegisterOutputParams(GH_OutputParamManager pManager)
    {
        pManager.AddTextParameter("Log", "Log", "Component log.", GH_ParamAccess.item);
    }

    protected override void SolveInstance(IGH_DataAccess da)
    {
        var rawItems = ReadAllInputValues();
        var refresh = false;

        if (rawItems.Count == 0)
        {
            da.SetData(0, "No input data.");
            return;
        }

        da.GetData(1, ref refresh);

        var parsedPairs = ParsePairs(rawItems).ToList();
        var desiredSchema = parsedPairs
            .Select(pair => new SchemaField(pair.Name, DetermineAccess(pair.Value)))
            .ToList();

        var log = new List<string>
        {
            $"Pairs: {parsedPairs.Count}",
            $"Stored schema: {_schema.Count}",
            $"Desired schema: {desiredSchema.Count}"
        };

        var shouldRefresh = (refresh || (_schema.Count == 0 && desiredSchema.Count > 0))
                            && !SchemaEquals(_schema, desiredSchema);

        if (shouldRefresh)
        {
            _pendingSchema = desiredSchema;
            log.Add(refresh ? "Scheduling schema refresh." : "Scheduling initial schema build.");
            OnPingDocument()?.ScheduleSolution(1, _ =>
            {
                if (_pendingSchema is null)
                {
                    return;
                }

                ApplySchema(_pendingSchema);
                _pendingSchema = null;
                ExpireSolution(true);
            });
        }
        else if (refresh)
        {
            log.Add("Refresh requested but schema is unchanged.");
        }

        if (_schema.Count != Params.Output.Count - 1)
        {
            log.Add("Output layout is out of sync. Trigger RefreshOutputs once.");
        }

        da.SetData(0, string.Join(Environment.NewLine, log));

        var max = Math.Min(parsedPairs.Count, _schema.Count);
        for (var i = 0; i < max; i++)
        {
            var outputIndex = i + 1;
            var field = _schema[i];
            var value = parsedPairs[i].Value;

            switch (field.Access)
            {
                case GH_ParamAccess.item:
                    da.SetData(outputIndex, value);
                    break;
                case GH_ParamAccess.list:
                    da.SetDataList(outputIndex, AsEnumerable(value));
                    break;
                case GH_ParamAccess.tree:
                    da.SetDataTree(outputIndex, BuildTree(value));
                    break;
                default:
                    da.SetData(outputIndex, value);
                    break;
            }
        }
    }

    public bool CanInsertParameter(GH_ParameterSide side, int index) => side == GH_ParameterSide.Output;

    public bool CanRemoveParameter(GH_ParameterSide side, int index) =>
        side == GH_ParameterSide.Output && index > 0;

    public IGH_Param CreateParameter(GH_ParameterSide side, int index)
    {
        if (side != GH_ParameterSide.Output)
        {
            return new Param_GenericObject();
        }

        return new Param_GenericObject();
    }

    public bool DestroyParameter(GH_ParameterSide side, int index) => side == GH_ParameterSide.Output && index > 0;

    public void VariableParameterMaintenance()
    {
        if (Params.Output.Count == 0)
        {
            return;
        }

        var logParam = Params.Output[0];
        logParam.Name = "Log";
        logParam.NickName = "Log";
        logParam.Description = "Component log.";
        logParam.Access = GH_ParamAccess.item;
        logParam.Optional = true;

        for (var i = 0; i < _schema.Count; i++)
        {
            var param = Params.Output[i + 1];
            var field = _schema[i];
            param.Name = field.Name;
            param.NickName = field.Name;
            param.Description = $"Database field '{field.Name}'.";
            param.Access = field.Access;
            param.Optional = true;
            param.MutableNickName = false;
        }
    }

    public override bool Write(GH_IWriter writer)
    {
        writer.SetInt32("SchemaCount", _schema.Count);
        for (var i = 0; i < _schema.Count; i++)
        {
            writer.SetString($"SchemaName_{i}", _schema[i].Name);
            writer.SetInt32($"SchemaAccess_{i}", (int)_schema[i].Access);
        }

        return base.Write(writer);
    }

    public override bool Read(GH_IReader reader)
    {
        _schema.Clear();

        if (reader.ItemExists("SchemaCount"))
        {
            var count = reader.GetInt32("SchemaCount");
            for (var i = 0; i < count; i++)
            {
                var name = reader.GetString($"SchemaName_{i}");
                var access = (GH_ParamAccess)reader.GetInt32($"SchemaAccess_{i}");
                _schema.Add(new SchemaField(name, access));
            }
        }

        var ok = base.Read(reader);
        RebuildOutputsFromSchema(preserveExistingParams: true);
        return ok;
    }

    private void ApplySchema(IReadOnlyList<SchemaField> nextSchema)
    {
        RecordUndoEvent("Refresh DB Outputs");
        _schema.Clear();
        _schema.AddRange(nextSchema);
        RebuildOutputsFromSchema(preserveExistingParams: false);
    }

    private void RebuildOutputsFromSchema(bool preserveExistingParams)
    {
        EnsureLogOutput();

        var desiredCount = _schema.Count + 1;
        if (!preserveExistingParams)
        {
            while (Params.Output.Count > 1)
            {
                Params.UnregisterOutputParameter(Params.Output[Params.Output.Count - 1], true);
            }
        }
        else
        {
            while (Params.Output.Count > desiredCount)
            {
                Params.UnregisterOutputParameter(Params.Output[Params.Output.Count - 1], true);
            }
        }

        for (var i = 0; i < _schema.Count; i++)
        {
            if (i + 1 < Params.Output.Count)
            {
                continue;
            }

            var field = _schema[i];
            var param = CreateSchemaOutputParam(field);
            Params.RegisterOutputParam(param);
        }

        Params.OnParametersChanged();
        VariableParameterMaintenance();
    }

    private void EnsureLogOutput()
    {
        if (Params.Output.Count > 0)
        {
            return;
        }

        Params.RegisterOutputParam(new Param_String
        {
            Name = "Log",
            NickName = "Log",
            Description = "Component log.",
            Access = GH_ParamAccess.item,
            Optional = true
        });
    }

    private static Param_GenericObject CreateSchemaOutputParam(SchemaField field)
    {
        return new Param_GenericObject
        {
            Name = field.Name,
            NickName = field.Name,
            Description = $"Database field '{field.Name}'.",
            Access = field.Access,
            Optional = true,
            MutableNickName = false
        };
    }

    private static bool SchemaEquals(IReadOnlyList<SchemaField> left, IReadOnlyList<SchemaField> right)
    {
        if (left.Count != right.Count)
        {
            return false;
        }

        for (var i = 0; i < left.Count; i++)
        {
            if (!string.Equals(left[i].Name, right[i].Name, StringComparison.Ordinal) ||
                left[i].Access != right[i].Access)
            {
                return false;
            }
        }

        return true;
    }

    private static object Unwrap(object value)
    {
        if (value is GH_ObjectWrapper wrapper)
        {
            return wrapper.Value;
        }

        if (value is IGH_Goo goo)
        {
            try
            {
                return goo.ScriptVariable();
            }
            catch
            {
                return goo;
            }
        }

        return value;
    }

    private static IEnumerable<(string Name, object Value)> ParsePairs(IEnumerable<object> items)
    {
        foreach (var item in items)
        {
            var unwrapped = Unwrap(item);

            if (TryEnumerateNestedPairs(unwrapped, out var nestedPairs))
            {
                foreach (var nestedPair in nestedPairs)
                {
                    yield return nestedPair;
                }

                continue;
            }

            if (TryParsePair(unwrapped, out var pair))
            {
                yield return pair;
                continue;
            }

            if (unwrapped != null && TryParsePair(unwrapped.ToString() ?? string.Empty, out pair))
            {
                yield return pair;
            }
        }
    }

    private static bool TryEnumerateNestedPairs(object? item, out List<(string Name, object Value)> pairs)
    {
        pairs = new List<(string Name, object Value)>();

        if (item is null || item is string)
        {
            return false;
        }

        if (item is not IEnumerable enumerable)
        {
            return false;
        }

        foreach (var child in enumerable.Cast<object>())
        {
            var unwrappedChild = Unwrap(child);

            if (TryParsePair(unwrappedChild, out var pair))
            {
                pairs.Add(pair);
                continue;
            }

            if (unwrappedChild != null &&
                TryParsePair(unwrappedChild.ToString() ?? string.Empty, out pair))
            {
                pairs.Add(pair);
                continue;
            }
        }

        return pairs.Count > 0;
    }

    private static bool TryParsePair(object item, out (string Name, object Value) pair)
    {
        switch (item)
        {
            case null:
                pair = default;
                return false;
            case string text when TryParsePythonTuple(text, out pair):
                return true;
            case DictionaryEntry entry:
                pair = (Convert.ToString(entry.Key) ?? "field", Unwrap(entry.Value));
                return true;
            case KeyValuePair<string, object> kv:
                pair = (kv.Key, Unwrap(kv.Value));
                return true;
            case IList list when list.Count >= 2:
                pair = (Convert.ToString(Unwrap(list[0])) ?? "field", Unwrap(list[1]));
                return true;
            case object[] array when array.Length >= 2:
                pair = (Convert.ToString(Unwrap(array[0])) ?? "field", Unwrap(array[1]));
                return true;
            default:
                var type = item.GetType();
                if (TryParseIndexableObject(item, type, out pair))
                {
                    return true;
                }

                var keyProp = type.GetProperty("Key");
                var valueProp = type.GetProperty("Value");
                if (keyProp != null && valueProp != null)
                {
                    var key = keyProp.GetValue(item, null);
                    var value = valueProp.GetValue(item, null);
                    pair = (Convert.ToString(Unwrap(key)) ?? "field", Unwrap(value));
                    return true;
                }

                pair = default;
                return false;
        }
    }

    private static GH_ParamAccess DetermineAccess(object value)
    {
        value = Unwrap(value);
        if (value is null)
        {
            return GH_ParamAccess.item;
        }

        if (value is string)
        {
            return GH_ParamAccess.item;
        }

        if (value is IEnumerable enumerable)
        {
            var values = enumerable.Cast<object>().Select(Unwrap).ToList();
            if (values.Count == 0)
            {
                return GH_ParamAccess.item;
            }

            return values.Any(v => v is IEnumerable && v is not string)
                ? GH_ParamAccess.tree
                : GH_ParamAccess.list;
        }

        return GH_ParamAccess.item;
    }

    private static IEnumerable AsEnumerable(object value)
    {
        value = Unwrap(value);
        if (value is string || value is null)
        {
            return new[] { value };
        }

        if (value is IEnumerable enumerable)
        {
            return enumerable.Cast<object>().Select(Unwrap).ToList();
        }

        return new[] { value };
    }

    private List<object> ReadAllInputValues()
    {
        var values = new List<object>();
        if (Params.Input.Count == 0)
        {
            return values;
        }

        var param = Params.Input[0];
        var data = param.VolatileData;
        if (data is null)
        {
            return values;
        }

        foreach (var path in data.Paths)
        {
            var branch = data.get_Branch(path);
            if (branch is null)
            {
                continue;
            }

            foreach (var item in branch)
            {
                values.Add(Unwrap(item));
            }
        }

        return values;
    }

    private static bool TryParseIndexableObject(object item, Type type, out (string Name, object Value) pair)
    {
        pair = default;

        var countProp = type.GetProperty("Count");
        var indexer = type
            .GetProperties(BindingFlags.Instance | BindingFlags.Public)
            .FirstOrDefault(p =>
            {
                if (!string.Equals(p.Name, "Item", StringComparison.Ordinal))
                {
                    return false;
                }

                var args = p.GetIndexParameters();
                return args.Length == 1 && args[0].ParameterType == typeof(int);
            });

        if (countProp == null || indexer == null)
        {
            return false;
        }

        try
        {
            var countValue = countProp.GetValue(item, null);
            var count = countValue is int i ? i : Convert.ToInt32(countValue);
            if (count < 2)
            {
                return false;
            }

            var first = indexer.GetValue(item, new object[] { 0 });
            var second = indexer.GetValue(item, new object[] { 1 });
            pair = (Convert.ToString(Unwrap(first)) ?? "field", Unwrap(second));
            return true;
        }
        catch
        {
            return false;
        }
    }

    private static bool TryParsePythonTuple(string text, out (string Name, object Value) pair)
    {
        pair = default;
        if (string.IsNullOrWhiteSpace(text))
        {
            return false;
        }

        var trimmed = text.Trim();
        if (!trimmed.StartsWith("(") || !trimmed.EndsWith(")"))
        {
            return false;
        }

        var inner = trimmed.Substring(1, trimmed.Length - 2);
        var parts = SplitTopLevel(inner);
        if (parts.Count < 2)
        {
            return false;
        }

        var name = ParsePythonLiteral(parts[0]) as string;
        if (string.IsNullOrWhiteSpace(name))
        {
            return false;
        }

        pair = (name ?? "field", ParsePythonLiteral(parts[1]));
        return true;
    }

    private static List<string> SplitTopLevel(string text)
    {
        var result = new List<string>();
        var current = new StringBuilder();
        var depthParen = 0;
        var depthBracket = 0;
        var inString = false;
        char stringQuote = '\0';

        foreach (var ch in text)
        {
            if (inString)
            {
                current.Append(ch);
                if (ch == stringQuote)
                {
                    inString = false;
                }

                continue;
            }

            switch (ch)
            {
                case '\'':
                case '"':
                    inString = true;
                    stringQuote = ch;
                    current.Append(ch);
                    break;
                case '[':
                    depthBracket++;
                    current.Append(ch);
                    break;
                case ']':
                    depthBracket--;
                    current.Append(ch);
                    break;
                case '(':
                    depthParen++;
                    current.Append(ch);
                    break;
                case ')':
                    depthParen--;
                    current.Append(ch);
                    break;
                case ',' when depthParen == 0 && depthBracket == 0:
                    result.Add(current.ToString().Trim());
                    current.Clear();
                    break;
                default:
                    current.Append(ch);
                    break;
            }
        }

        if (current.Length > 0)
        {
            result.Add(current.ToString().Trim());
        }

        return result;
    }

    private static object ParsePythonLiteral(string text)
    {
        var trimmed = text.Trim();
        if (trimmed.Length == 0)
        {
            return string.Empty;
        }

        if ((trimmed.StartsWith("'") && trimmed.EndsWith("'")) ||
            (trimmed.StartsWith("\"") && trimmed.EndsWith("\"")))
        {
            return trimmed.Substring(1, trimmed.Length - 2);
        }

        if (string.Equals(trimmed, "True", StringComparison.OrdinalIgnoreCase))
        {
            return true;
        }

        if (string.Equals(trimmed, "False", StringComparison.OrdinalIgnoreCase))
        {
            return false;
        }

        if (int.TryParse(trimmed, out var intValue))
        {
            return intValue;
        }

        if (double.TryParse(trimmed, out var doubleValue))
        {
            return doubleValue;
        }

        if (trimmed.StartsWith("[") && trimmed.EndsWith("]"))
        {
            var inner = trimmed.Substring(1, trimmed.Length - 2);
            if (string.IsNullOrWhiteSpace(inner))
            {
                return new List<object>();
            }

            return SplitTopLevel(inner).Select(ParsePythonLiteral).ToList();
        }

        return trimmed;
    }

    private static GH_Structure<IGH_Goo> BuildTree(object value)
    {
        var tree = new GH_Structure<IGH_Goo>();
        value = Unwrap(value);

        if (value is null || value is string)
        {
            tree.Append(new GH_ObjectWrapper(value), new GH_Path(0));
            return tree;
        }

        if (value is not IEnumerable enumerable)
        {
            tree.Append(new GH_ObjectWrapper(value), new GH_Path(0));
            return tree;
        }

        var outer = enumerable.Cast<object>().Select(Unwrap).ToList();
        if (outer.Count == 0)
        {
            return tree;
        }

        var hasNested = outer.Any(v => v is IEnumerable && v is not string);
        if (!hasNested)
        {
            foreach (var item in outer)
            {
                tree.Append(new GH_ObjectWrapper(item), new GH_Path(0));
            }

            return tree;
        }

        for (var branchIndex = 0; branchIndex < outer.Count; branchIndex++)
        {
            var branchValue = Unwrap(outer[branchIndex]);
            var path = new GH_Path(branchIndex);

            if (branchValue is IEnumerable branchEnumerable && branchValue is not string)
            {
                foreach (var item in branchEnumerable.Cast<object>().Select(Unwrap))
                {
                    tree.Append(new GH_ObjectWrapper(item), path);
                }
            }
            else
            {
                tree.Append(new GH_ObjectWrapper(branchValue), path);
            }
        }

        return tree;
    }

    private static class DbFieldsToOutputsIcon
    {
        public static Bitmap Create()
        {
            var bmp = new Bitmap(24, 24);
            using var g = Graphics.FromImage(bmp);
            g.SmoothingMode = SmoothingMode.AntiAlias;
            g.Clear(Color.Transparent);

            using var bg = new SolidBrush(Color.FromArgb(33, 76, 62));
            using var panel = new SolidBrush(Color.FromArgb(235, 228, 196));
            using var accent = new SolidBrush(Color.FromArgb(196, 142, 54));
            using var wire = new Pen(Color.FromArgb(60, 60, 60), 1.6f);
            using var textBrush = new SolidBrush(Color.FromArgb(25, 25, 25));
            using var smallFont = new Font("Microsoft YaHei UI", 6.8f, FontStyle.Bold, GraphicsUnit.Pixel);

            FillRoundedRectangle(g, bg, 1, 1, 22, 22, 5);
            g.FillRectangle(accent, 3, 4, 8, 3);
            g.FillRectangle(accent, 3, 9, 8, 3);
            g.FillRectangle(accent, 3, 14, 8, 3);

            g.DrawLine(wire, 12, 6, 16, 6);
            g.DrawLine(wire, 12, 11, 16, 11);
            g.DrawLine(wire, 12, 16, 16, 16);
            g.DrawLine(wire, 16, 6, 19, 9);
            g.DrawLine(wire, 16, 11, 19, 11);
            g.DrawLine(wire, 16, 16, 19, 13);

            g.FillEllipse(bg, 17, 7, 4, 4);
            g.FillEllipse(bg, 17, 10, 4, 4);
            g.FillEllipse(bg, 17, 13, 4, 4);
            g.DrawEllipse(wire, 17, 7, 4, 4);
            g.DrawEllipse(wire, 17, 10, 4, 4);
            g.DrawEllipse(wire, 17, 13, 4, 4);

            g.DrawString("DB", smallFont, textBrush, new PointF(3.2f, 18.1f));

            return bmp;
        }

        private static void FillRoundedRectangle(Graphics g, Brush brush, float x, float y, float width, float height, float radius)
        {
            using var path = new GraphicsPath();
            var diameter = radius * 2;
            path.AddArc(x, y, diameter, diameter, 180, 90);
            path.AddArc(x + width - diameter, y, diameter, diameter, 270, 90);
            path.AddArc(x + width - diameter, y + height - diameter, diameter, diameter, 0, 90);
            path.AddArc(x, y + height - diameter, diameter, diameter, 90, 90);
            path.CloseFigure();
            g.FillPath(brush, path);
        }
    }
}
