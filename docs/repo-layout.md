# Repository Layout

This repository now uses a single-repo, dual-project layout:

```text
src/yingzao/                  # PyPI package and Python core logic
grasshopper/YingZao.GH/       # C# Grasshopper plugin project
dist/                         # Built Python and Grasshopper artifacts
docs/                         # Project notes and architecture docs
```

Publishing:

- Python core: PyPI
- Grasshopper plugin: `.gha` artifact / Rhino package / GitHub release
