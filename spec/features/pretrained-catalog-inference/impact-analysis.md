# Impact: Pretrained Catalog Inference

Catalog metadata gains optional fields; legacy records must remain readable and
usable for training. New queue messages share an existing trigger, so dispatch
must not overwrite authoritative records or change legacy payload behavior.

DINOv3 needs a compatible Transformers implementation and offline backbone
configuration. Validate package changes against legacy training and inference.
An unavailable model asset blocks model activation, not unrelated catalog/UI
work.

Class remapping and NoData are correctness boundaries: raw background is not
NoData, damage is value 3 in HASTE, and output building IDs must stay aligned
with source footprints. Source checkpoints and previous runs are read-only.

## Security Impact

The dedicated image uses official PyTorch CUDA 12.8 wheels pinned by URL and
SHA-256 for Python 3.10/Linux x86_64, plus exact Transformers 5.5.4,
huggingface-hub 1.30.0 and tokenizers 0.22.2 pins. Official PyPI release metadata
confirmed these packages exist, are not yanked, and support the image's Python.
The live OSV exact-version query was performed on 2026-09-09.

| Candidate issue | Decision for this path |
|---|---|
| Torch 2.8 restricted-loader memory corruption, [CVE-2026-24747](https://github.com/pytorch/pytorch/security/advisories/GHSA-63cw-57p8-fm3p) | Reject the initial 2.8 candidate. Use Torch 2.10.0 with torchvision 0.25.0; raise the DINOv3 restricted-loader floor to 2.10. |
| Torch 2.10 [JIT scripting issue](https://github.com/advisories/GHSA-rrmf-rvhw-rf47) and [PT2 loading issue](https://github.com/pytorch/pytorch/pull/176791) | Neither JIT scripting of user code nor PT2 loading is used. The runtime constructs an allowlisted model and loads a hashed state dictionary. These are not claims that Torch is generally vulnerability-free. |
| Transformers 5.5.4 [CVE-2026-9856](https://github.com/advisories/GHSA-xrqw-3rrv-vx5w), tokenizer/processor `save_pretrained` chat-template paths | This path never loads or saves tokenizers/processors or chat templates. Keep the checkpoint-compatible version; do not broaden it to Hub-controlled model/processor code. |
| Hub 1.30.0, tokenizers 0.22.2, torchvision 0.25.0 | No exact-version OSV advisories were returned at review time; this is scoped evidence, not a security guarantee. |

Jobs receive approved checkpoint/config assets from configured storage and
verify their hashes before restricted deserialization. `weights_only=True` and
strict state matching are not general-purpose sandboxes. Do not accept arbitrary
browser-supplied model files, Hub code, Python modules, or shell commands.

The legacy training image retains its existing dependencies. The new image
installs its own ML stack without altering that image or shared host
environments. Functional tests in the initial host environment were not a
hermetic image proof; the dedicated image build and GPU validation are separate
acceptance steps. No credential is stored in recipe JSON or image layers.
