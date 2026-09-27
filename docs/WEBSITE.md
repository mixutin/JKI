# Jake AI website and GitHub Pages

The static site lives in `website/`. Its documentation is generated directly from this repository's
Markdown files. It includes a responsive landing page, a procedural WebGL orb, a static orb fallback,
reduced-motion support, a user-controlled preview, local documentation search, a sitemap, metadata,
and a custom 404 page. There is no browser microphone access or AI service connection.

## Build and preview

From the repository root:

```sh
python -m pip install -r website/requirements.txt
python website/build.py
python -m http.server 8000 --directory _site
```

The default build targets the upstream project path `/JKI/`. For the local preview above, build with
a root URL first and open `http://localhost:8000`:

```sh
python website/build.py --base-url http://localhost:8000
```

The builder verifies internal links, fragment targets, and referenced assets. It fails on unresolved
template fields and broken internal links. To test project-path hosting, serve the build under `/JKI/`
or inspect the normal GitHub Pages build artifact.

## Automatic publishing

`.github/workflows/pages.yml` builds and validates the site on branch pushes and every pull request targeting `main`.
Pull requests upload a downloadable `github-pages` artifact; they do not deploy the production site.
Pushes to `main` and manual runs on `main` build and deploy through GitHub's Pages actions. Other manual
branches can build but cannot deploy.

A repository administrator must select **Settings → Pages → Build and deployment → Source → GitHub
Actions** once. Protect the `github-pages` environment so deployment is allowed from `main`. Merge this
PR, then inspect the Pages workflow. The normal upstream URL is `https://ridjan-xhika.github.io/JKI/`.
The workflow uses Pages metadata on production builds, so project paths and configured custom domains
receive matching canonical URLs and asset paths. PR builds derive the normal URL from the repository.

Only the deployment job receives `pages: write` and `id-token: write`. PR code runs with read permissions.
Actions are pinned to reviewed commit SHAs and Dependabot checks the workflow dependencies.

## Editing the design

- `website/home.html`: landing page content and interactive preview.
- `website/layout.html`: shared header, footer, metadata, and search dialog.
- `website/assets/style.css`: responsive styles and reduced-motion rules.
- `website/assets/orb.glsl` and `orb.js`: the procedural 3D orb and motion lifecycle.
- `website/assets/main.js`: search, copy controls, preview, and mobile docs navigation.
- `website/build.py`: document routes, Markdown rendering, and link validation.

The orb caps rendering resolution and frame rate, stops when off screen or in a hidden tab, and starts
paused when reduced motion is requested. If WebGL is unavailable, a CSS illustration remains visible.
The interactive preview is clearly labelled as a design preview, not a desktop screenshot.

Check desktop and mobile widths, keyboard navigation, search, copy buttons, reduced motion, and WebGL
fallback before publishing visual changes. Preview controls are local demonstrations and should remain
independent of the user's microphone or account.
