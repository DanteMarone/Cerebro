# Vendored front-end dependencies

No npm at runtime, no bundler, no CDN. Client libraries are committed here as the **unmodified
upstream ESM builds**, extracted from the npm tarball and verified against the registry's own
published integrity digest.

## How these files got here

`python scripts/vendor_fetch.py` — the only supported way to add or update a file in this
directory. It downloads the tarball from `registry.npmjs.org`, checks it against the
`dist.integrity` digest the registry publishes for that exact version, and extracts only the ESM
builds. A mismatch aborts.

**Never hand-write a file here.** A previous revision of this directory contained a 25 KB
"Preact standalone bundle" and a 3.6 KB "htm" that were plausible reimplementations rather than
the published artifacts. The htm one silently rendered nothing — no exception, no console error,
200 on every request — and the entire UI came up blank while the test suite stayed green. The
SHA-256 digests recorded alongside them were hashes of those local files, so they attested to
nothing. A fabricated dependency carrying an authoritative-looking hash is worse than an unhashed
one, because it defeats the check it appears to pass.

## Contents

| File | Package | Version | Bytes | SHA-256 |
| :--- | :--- | :--- | ---: | :--- |
| `preact.module.js` | preact | 10.23.2 | 11591 | `2748f7512971d18489c490a3ef8b81aa373fd469eb1ff28107b591e824e0dd2f` |
| `hooks.module.js` | preact (hooks) | 10.23.2 | 3729 | `896fc8e546b96c3fca29743b493293820ad4e76396fd36ff05f18a52eaf303e1` |
| `htm.module.js` | htm | 3.1.1 | 1207 | `ab33dd3f38059b9be4d5f5350128eefb2356639c4e0bbe9d9e8b3ba75847e9e4` |

Tarballs, verified against the registry `sha512` integrity digest at fetch time:

- `https://registry.npmjs.org/preact/-/preact-10.23.2.tgz`
- `https://registry.npmjs.org/htm/-/htm-3.1.1.tgz`

Licences: Preact MIT, htm Apache-2.0.

## Import map

`hooks.module.js` is unmodified upstream and therefore imports the bare specifier `preact`. Rather
than editing vendored bytes, `index.html` declares an import map:

```json
{ "imports": { "preact": "/static/vendor/preact.module.js",
               "preact/hooks": "/static/vendor/hooks.module.js" } }
```

`app.js` imports `preact` and `preact/hooks` through that map, and `htm.module.js` by relative
path. `htm.module.js` is currently unused — `app.js` builds its tree with `h()` directly — but is
kept vendored and verified so templates can be reintroduced without another fetch.
