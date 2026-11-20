# Third-party data in Bento's ethics library

`agentos/ethics_library.json` is built by `agentos/ethicslib.py` from the sources below. Each one
is permissively licensed; this file carries the notices their licences ask a copy to carry.

## MITRE ATT&CK®

Program names, malware names and technique names are taken from MITRE ATT&CK (Enterprise),
from https://github.com/mitre-attack/attack-stix-data. Its licence, reproduced as it asks:

```
License
-------
The MITRE Corporation (MITRE) hereby grants you a non-exclusive, royalty-free license to use ATT&CK® for research,
development, and commercial purposes. Any copy you make for such purposes is authorized provided that you reproduce
MITRE's copyright designation and this license in any such copy.

"© 2026 The MITRE Corporation. This work is reproduced and distributed with the permission of The MITRE Corporation."

Disclaimers
-----------
MITRE does not claim ATT&CK enumerates all possibilities for the types of actions and behaviors documented as part
of its adversary model and framework of techniques. Using the information contained within ATT&CK to address or cover
full categories of techniques will not guarantee full defensive coverage as there may be undisclosed techniques or
variations on existing techniques not documented by ATT&CK.

ALL DOCUMENTS AND THE INFORMATION CONTAINED THEREIN ARE PROVIDED ON AN "AS IS" BASIS AND THE CONTRIBUTOR, THE
ORGANIZATION HE/SHE REPRESENTS OR IS SPONSORED BY (IF ANY), THE MITRE CORPORATION, ITS BOARD OF TRUSTEES, OFFICERS,
AGENTS, AND EMPLOYEES, DISCLAIM ALL WARRANTIES, EXPRESS OR IMPLIED, INCLUDING BUT NOT LIMITED TO ANY WARRANTY THAT
THE USE OF THE INFORMATION THEREIN WILL NOT INFRINGE ANY RIGHTS OR ANY IMPLIED WARRANTIES OF MERCHANTABILITY OR
FITNESS FOR A PARTICULAR PURPOSE.
```

## MITRE ATLAS™

Technique names are taken from MITRE ATLAS, https://github.com/mitre-atlas/atlas-data.

Copyright 2021-2026 MITRE. Licensed under the Apache License, Version 2.0 (the "License");
you may not use this file except in compliance with the License. You may obtain a copy of
the License at http://www.apache.org/licenses/LICENSE-2.0. Unless required by applicable law
or agreed to in writing, software distributed under the License is distributed on an "AS IS"
BASIS, WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
License for the specific language governing permissions and limitations under the License.

Bento changed it: only technique names and ids are kept, sorted into Bento's own categories
and weighted by Bento.

## MIT AI Risk Repository

Only the names of the domain taxonomy's categories are used, to sort flags. Slattery, P., et
al. (2024). The AI Risk Repository: A Comprehensive Meta-Review, Database, and Taxonomy of
Risks From Artificial Intelligence. arXiv:2408.12622. https://airisk.mit.edu. Licensed
CC BY 4.0, https://creativecommons.org/licenses/by/4.0/. The names are shortened here.

MITRE ATT&CK and ATT&CK are registered trademarks, and ATLAS a trademark, of The MITRE
Corporation. Their use here describes where the data came from and implies no endorsement.
