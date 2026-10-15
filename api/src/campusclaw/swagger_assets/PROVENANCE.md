# Swagger UI static assets

- Upstream: https://github.com/swagger-api/swagger-ui
- Distribution: npm `swagger-ui-dist@5.17.14` (supports OpenAPI 3.1).
- Source: https://registry.npmjs.org/swagger-ui-dist/-/swagger-ui-dist-5.17.14.tgz
- License: Apache-2.0, retained verbatim in `LICENSE`.
- The runtime bundle and stylesheet are copied without modification. The eight `csp-image-*` files are byte-for-byte decodings of the stylesheet's data-image URLs (base64 or URL decoding as appropriate). `local.css` overrides only their background-image URLs to use those same-origin files. This preserves icons without permitting `data:` images in the gateway CSP.
- Assets are packaged with the API and served at `/api/docs/assets/`. No runtime CDN or external documentation requests are needed. Initialization is a separate same-origin script, so the gateway CSP is unchanged.
- Update by explicitly selecting a compatible upstream version, copying these three files from its npm tarball, updating these hashes, re-decoding its CSS data images and matching the `local.css` selectors, and rerunning OpenAPI/Swagger browser tests. Do not hand-edit minified assets.

SHA-256:

```text
c57badf459aa6e65cc036b3862d0502a63f9a22546407ffcb0e64f85f816bb28  swagger-ui-dist-5.17.14.tgz
cfc7749b96f63bd31c3c42b5c471bf756814053e847c10f3eb003417bc523d30  LICENSE
40170f0ee859d17f92131ba707329a88a070e4f66874d11365e9a77d232f6117  swagger-ui.css
c2e4a9ef08144839ff47c14202063ecfe4e59e70a4e7154a26bd50d880c88ba1  swagger-ui-bundle.js
```
