# orange-canvas-core (WASM fork)

Experimental fork of [orange-canvas-core](https://github.com/biolab/orange-canvas-core) for running
Orange3 in the browser via Pyodide + PyQt6 WASM.

Forked from upstream [`0.2.8`](https://github.com/biolab/orange-canvas-core/tree/0.2.8)
(commit `3a64d35`).

## Changes

Replaced `exec()` calls with `open()` equivalents and removed blocking dialog patterns
that are incompatible with the single-threaded WASM event loop. Key areas:

- `application/canvasmain.py`: Removed blocking dialogs, replaced with non-blocking alternatives
- `application/addons.py`, `settings.py`: Disabled addon/settings features that require subprocess/threading
- `document/interactions.py`, `schemeedit.py`: Replaced exec-based interactions with open-based equivalents
- `document/quickmenu.py`: Non-blocking quick menu
- `gui/utils.py`: Replaced modal message boxes with non-blocking versions

## Install (Pyodide)

```python
await micropip.install(
    "https://team-monolith-product.github.io/orange-canvas-core/orange_canvas_core-0.2.8-py3-none-any.whl"
)
```

## Release procedure

1. Make changes on `master` and commit.

2. Build the wheel:

```bash
python -m build --wheel
```

3. Create a GitHub Release:

```bash
gh release create wasm-{version} dist/orange_canvas_core-{version}-py3-none-any.whl \
    --title "{version}-wasm" --notes "..."
```

4. Deploy to GitHub Pages (serves the wheel with CORS):

```bash
git checkout gh-pages
cp dist/orange_canvas_core-{version}-py3-none-any.whl .
git add *.whl
git commit -m "deploy: orange_canvas_core-{version}-py3-none-any.whl"
git push origin gh-pages
git checkout master
```
