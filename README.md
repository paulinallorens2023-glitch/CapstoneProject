# GitHub Pages dashboard package

This folder contains a static interactive HTML dashboard generated from the executed AT&T capstone notebook outputs.

## Files
- `index.html` — upload this to the root of your GitHub repo for GitHub Pages.
- `outputs/` — authoritative/dashboard/diagnostics/docs files copied from the model run for traceability.

## Notes
- Historical Excel inputs were used to run the model and were not modified.
- This static dashboard does not execute Python on GitHub Pages; it displays the results already exported by the notebook.
- To publish: upload `index.html` and optionally the `outputs/` folder to your repo, then enable GitHub Pages on the `main` branch root.
