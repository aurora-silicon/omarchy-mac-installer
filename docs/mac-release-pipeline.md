# Mac release pipeline

`.github/workflows/mac-release-pipeline.yml` runs one edge image, the one every M1, M2 and M3 Mac takes, from build to a signed edge catalog, and beside it builds the MacBook Neo's own image, which the edge catalog offers once a recorded install on a real Neo vouches for it (see [The MacBook Neo image](#the-macbook-neo-image)). `edge-dispatch.yml` starts it (`dry-run=false`, on `main`) when an edge publish changes a package the image installs. You can also start it by hand, and a manual run is a dry run unless you say otherwise. The only manual step is the owner's approval of the catalog signature.

| Job | Workflow | Runs when | Gates it keeps |
| --- | --- | --- | --- |
| `plan` | here | always | every run starts only from `main`, dry runs included (the image builds only from `main`), never for a pull request |
| `build` | `mac-image.yml` | after `plan` | no secrets; the release guard; a build attestation on the zip |
| `acceptance` | `mac-acceptance.yml` | after `build` | main only, never for a pull request; the zip's sha256 and build attestation checked; the VM harness's `fresh-install` scenarios on the VM runner ([runner](mac-acceptance-runner.md)); fails unless the evidence record for the zip's sha256 passes; a passing record is attested |
| `catalog-inputs` | here | acceptance passed | `.github/mac-release-pipeline.json` must name an app release (a dry run only notes it), before anything is public |
| `upload` | `mac-upload.yml` | acceptance `result == pass`, catalog inputs read | `publish` environment (main only); evidence and attestation re-checked; never overwrites; publishes the draft as a prerelease (never latest) on a real run |
| `neo-recovery` | here | after `plan` | builds the native Recovery app on `macos-26`, as `neo-image.yml` does |
| `neo-build` | `mac-image.yml` (`hardware-profile: neo`) | after `neo-recovery` | the same build, release guard and attestation as `build`; IMAGE must record `hardware_profile=neo` |
| `neo-evidence` | here | the dispatcher supplied `neo-hardware-evidence` | the record's form (`scripts/hardware_evidence.py`), edge only, and `neo-image-run-id` |
| `neo-upload` | `mac-upload.yml` | `neo-evidence` and `upload` succeeded | the record in place of VM evidence: its image and sha256, and IMAGE and `installer_data.json` built for the Neo alone; the earlier run must be a successful `main` run; the build attestation as for `upload` |
| `neo` | here | always (unless cancelled) | hands the catalog the new Neo inputs when `neo-evidence` and `neo-upload` passed, otherwise warns in the run summary and hands it nothing |
| `neo-build-report` | here | after `neo-build` (unless cancelled) | names this run's Neo image for a tester, or warns that it did not build; nothing waits for it |
| `catalog` | `mac-catalog.yml` | real run, every M1, M2 and M3 job above and `neo` succeeded | evidence re-checked for each payload's digest; each image's `installer_data.json` admits exactly the Macs it is given; every URL serves its pinned bytes; without new Neo inputs, carries the published Neo forward if it still checks out; `catalog-release` (owner approval, main only) signs |

A dry run uploads to a `dryrun-` scratch release and deletes it, and signs no catalog. A catalog dry run needs files the app can download, so run `mac-catalog.yml` by hand for that.

## What passes between jobs

- `build` outputs `name` (also the image artifact's name), `payload` (the zip's file name) and `sha256`.
- The image never leaves Namespace: `build` (on Namespace's Apple-backed Linux ARM64 runner), `acceptance` and `upload` (on Namespace runners) pass it through Namespace's artifact storage (`namespace-actions/upload-artifact` and `download-artifact`), about 10 s for the 3.4 GB zip each way. No pull request reaches a Namespace runner: acceptance's VM job waits for its GitHub-hosted `guard`, and the build and upload jobs carry the same refusal in their own `if:` (the build also requires `main`). The small artifacts (evidence, logs) stay GitHub artifacts.
- `acceptance` uploads the artifact `acceptance-evidence`, holding `acceptance-evidence.json` ([format](mac-acceptance-evidence.md)), and outputs `result`, `evidence-artifact` and `evidence-run-id` (this run). It also keeps the harness's logs as `acceptance-harness-logs`. The pipeline's `runner` input (empty by default) overrides the VM job's runner.
- `upload` downloads the image and evidence artifacts from this run. After a real upload it outputs `payload` and `installer-data` (the catalog's inputs, built from the files it uploaded and verified) and `evidence` (the record it checked).
- `catalog-inputs` outputs the `engine` and `installer` blocks of `.github/mac-release-pipeline.json`.
- `neo-build` outputs the Neo image's `name`, `payload` and `sha256` like `build`; the image artifact is named after the image, whose package set differs from the M1, M2 and M3 one, so the two never share an artifact, a release or an `evidenceRevision` (their zips share a file name, each under its own release). The Recovery app passes as the artifact `neo-native-recovery-input`.
- `neo-evidence` outputs the record's `image`, `sha256` and the record itself; `neo-upload` outputs `payload`, `installer-data` and `evidence` like `upload`; `neo` passes them to `catalog` as `neo-image`, `neo-payload`, `neo-installer-data` and `neo-evidence`, or passes empty strings.

## The MacBook Neo image

The Neo boots its own image (`hardware_profiles` in `scripts/supported-models.json`): Aurora's J700 Stage 1 and Stage 2, the Aurora kernel and an `installer_data.json` that admits only `j700ap`. The M1, M2 and M3 image excludes `j700ap`. The VM harness cannot test it: `tools/acceptance/mac-image/run` (pinned in `mac-acceptance.yml`) boots QEMU's `virt` machine with a generic Arch Linux ARM kernel, the image's initramfs and a device tree whose root compatible is fixed to an M1 Pro (`apple,j314s`, `apple,t6000`). It never runs m1n1, Stage 1 or the Aurora kernel, cannot present a J700, and has no input that changes the board. A VM run of the Neo image would test its userland as an M1 Pro, which says nothing about a Neo. So the Neo image's gate is a recorded install on a real Neo instead, on edge only:

1. Any pipeline run (an automatic one or a dry run) builds a Neo image, keeps it 14 days as a workflow artifact and names it, with its sha256 and the run id, in the run summary.
2. A tester installs that exact zip on a MacBook Neo with app 2.3.0 or later and writes the hardware install record ([format](catalog-release.md#hardware-install-record)).
3. The owner dispatches the pipeline by hand with `neo-hardware-evidence` (the record) and `neo-image-run-id` (that run). The run builds the M1, M2 and M3 image as usual, uploads the recorded Neo image from the earlier run with the record as its evidence (published beside it as `hardware-evidence.json`), and the catalog offers it to the Neo alone. The owner reviews the record in the `catalog-release` approval.

Every later run without a new record, `edge-dispatch.yml`'s included, carries that Neo image forward, so the Neo stays on edge. `mac-catalog.yml`'s `prepare` reads the published edge catalog (verified against the trust root), takes its Neo entry's payload and `installer_data.json` pins and the `hardware-evidence.json` beside the payload, which must match the record digest that catalog signed (`qualificationEvidence`), carries only an enabled entry of a catalog that passes the current Mac policy, and runs every Neo check again: the record against the payload digest, the board and the new catalog's `installer.minimumVersion`; every pinned asset downloaded against its size and digest; the `installer_data.json` admitting only `j700ap`. The `prepare` output and the run summary say whether the Neo image is new, carried or dropped. A new record replaces the carried entry. The catalog never waits for the current run's `neo-build`; that build only gives a tester the next image.

A Neo failure never holds back or changes the M1, M2 and M3 image. When the record check, upload, a download or any `prepare` check fails for the new or carried Neo image, the catalog is built and signed without it, and the run summary carries a warning. Only the record of a Neo the catalog carries reaches the signing job. rc and stable never take the Neo image: promotion refuses a catalog with more than one image, and hardware evidence is refused off edge.

## Where the jobs run

Namespace builds and publishes the image. Namespace is a Distinguished Corporate Patron of the Omacom Foundation, giving $100,000 a year in compute for three years for ARM builds and QA ([announcement](https://omarchy.org/news/2026/10/namespace-joins-as-a-distinguished-corporate-patron/)), so its runners are our CI, like GitHub's. `build` runs on Namespace's Apple-backed Linux ARM64 runner. `upload` runs on a Namespace runner too, with `contents: write` in the `publish` environment (and, once ticket 13 adds it, the R2 token). It is the first job with write access that runs off GitHub's hosted runners. The guards and the jobs that hold `id-token`, `attest` in `mac-image.yml` and in `mac-acceptance.yml`, stay on GitHub-hosted runners.

So when acceptance and upload run `gh attestation verify --deny-self-hosted-runners`, they check that the attestation was signed by `mac-image.yml` on `main` in its GitHub-hosted `attest` job, over the digest `build` reported. They do not check that the zip was built on a GitHub-hosted runner: Namespace built it.

## Secrets

The only secret is `CATALOG_SIGNING_KEY`, an environment secret of `catalog-release`. The pipeline passes it to `mac-catalog.yml` by name and never uses `secrets: inherit`. GitHub delivers an environment secret to a called workflow only when the caller passes it, and only to the job that runs in that environment. A throwaway probe (run 38553165283) confirmed this: passed by name or with inherit, the secret reached the job in the environment but not a job without it, and not passed, it reached neither. A second probe (run 38558712893) checked one more level of nesting, which is what happens once #69 moves signing into `mac-catalog-sign.yml`: when the pipeline passes the key by name and `mac-catalog.yml` forwards it, by name or with `inherit`, the key reaches the sign job. When the pipeline passes nothing, it stays empty. `mac-catalog.yml` can only forward what it was given, which here is the key alone. When ticket 13 puts an R2 token in `publish`, the pipeline's `upload` job must pass that token by name in the same way.

The catalog takes the evidence record the upload checked, and the upload took it from this run's acceptance artifact, with the attestation `mac-acceptance.yml`'s `attest` job made for it. The acceptance workflow uses no secrets.

## `.github/mac-release-pipeline.json`

- `engine`: the catalog's engine block ([format](catalog-release.md#inputs)). It is the engine `Packaging/build-app.sh` pins, published as the `engine-v0.9.2-omarchy.28` release. Ticket 13 moves it to `mac.omarchy.org/v1/engine/`. A test keeps this block in step with `build-app.sh` and `Engine/source-lock.json`.
- `installer`: the app compatibility block, `{"minimumVersion", "latestVersion", "downloadURL"}`. The edge catalog requires app 2.3.0, the first release whose edge catalog offers the Neo, and a catalog with the Neo image refuses anything older. `downloadURL` is `null` until `mac-app-release.yml` publishes 2.3.0 (push the tag `v2.3.0`), and on a real run `catalog-inputs` refuses with a message saying so, before the upload, so nothing is made public. `null` for the whole block means no app release at all, with the same refusal.

> **Before this merges:** release installer 2.3.0 and set `downloadURL` to its published `.dmg`. Until then every real pipeline run, M1, M2 and M3 edge updates included, stops at `catalog-inputs`. `minimumVersion` 2.3.0 also makes every edge user, M1, M2 and M3 included, update the app before the next install.
