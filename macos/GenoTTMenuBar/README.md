# Geno TT menu bar app

A minimal native macOS app that lives in the menu bar and stays out of the
Dock. It currently shows a small placeholder popover and a Quit action.

Requires macOS 13 or newer. Build the signed development app bundle with:

```bash
./Scripts/build-app.sh
```

The bundle is written to `dist/Geno TT.app`. Install and launch it with:

```bash
mkdir -p "$HOME/Applications"
ditto "dist/Geno TT.app" "$HOME/Applications/Geno TT.app"
open "$HOME/Applications/Geno TT.app"
```

The development bundle is ad-hoc signed for local use. Distribution will need
a Developer ID signature and notarization.
