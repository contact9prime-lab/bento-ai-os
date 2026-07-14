# Third-party notices

AgentOS is licensed under the MIT License (see `LICENSE`). It bundles or
depends on the third-party components below.

## Bundled assets

### xterm.js 5.3.0 (MIT)

Files: `agentos/ui/assets/xterm.js`, `agentos/ui/assets/xterm-addon-fit.js`,
`agentos/ui/assets/xterm.css` — minified builds of
[xterm.js](https://github.com/xtermjs/xterm.js).

```
Copyright (c) 2017-2022, The xterm.js authors (https://github.com/xtermjs/xterm.js)
Copyright (c) 2014-2016, SourceLair Private Company (https://www.sourcelair.com)
Copyright (c) 2012-2013, Christopher Jeffrey (https://github.com/chjj/)

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in
all copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN
THE SOFTWARE.
```

## Python dependencies

### certifi (MPL-2.0)

[certifi](https://github.com/certifi/python-certifi) is a required transitive
dependency of `httpx` and ships unmodified under the Mozilla Public License
2.0 (https://mozilla.org/MPL/2.0/). Its complete source code is available at
the repository above. AgentOS does not modify certifi; at runtime it prefers
the operating system's certificate store via `truststore`.

### Other dependencies (permissive)

All other Python dependencies, direct and transitive, are distributed under
permissive licenses:

| License | Packages |
|---|---|
| MIT / MIT-0 | fastapi, mcp, textual, truststore, pydantic, pydantic-core, pydantic-settings, rich, anyio, attrs, jsonschema, jsonschema-specifications, referencing, rpds-py, markdown-it-py, mdit-py-plugins, mdurl, linkify-it-py, uc-micro-py, httpx-sse, h11, PyJWT, platformdirs, annotated-types, annotated-doc, typing-inspection, cffi |
| BSD (2/3-Clause) | uvicorn, httpx, httpcore, websockets, starlette, sse-starlette, click, idna, pycparser, python-dotenv, Pygments |
| Apache-2.0 | python-multipart, cryptography (Apache-2.0 OR BSD-3-Clause) |
| PSF-2.0 | typing_extensions |

Each package's full license text is included in its `*.dist-info` directory
in the installed environment.
