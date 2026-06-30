# Jenkins Pipeline Manual

This directory contains the Jenkins pipeline used to build and publish the OAI gNB container image for the FHI 7.2 flow.

## Files

- `Jenkinsfile`: Declarative Jenkins pipeline for cloning OpenAirInterface, building the base/build/gNB images with Podman, and pushing the final image to the configured registry.

## Prerequisites

The Jenkins agent must provide:

- Linux shell environment
- `git`
- `podman`
- Network access to the configured Git repository, upstream dependency sources, and container registry
- Permission to build containers with Podman

The Jenkins instance must also define these credentials:

- `GIT_CREDENTIAL_ID`: Git credential used to clone the OAI repository. The default pipeline value is `ming_gh_token`.
- `REGISTRY_CREDENTIAL_ID`: Username/password credential used for registry login. The default pipeline value is `ming_account`.

## Jenkins Job Setup

1. Create a new Jenkins Pipeline job.
2. Configure the job to use `Pipeline script from SCM`, or paste the content of `Jenkins/Jenkinsfile` directly into the pipeline script field.
3. If using SCM, set the script path to:

   ```text
   Jenkins/Jenkinsfile
   ```

4. Run the job once so Jenkins registers the pipeline parameters.
5. Re-run the job with the desired parameter values.

## Parameters

| Parameter | Default | Description |
| --- | --- | --- |
| `GIT_REPO` | `https://github.com/bmw-ece-ntust/openairinterface5g` | OAI source repository to clone. |
| `GIT_BRANCH` | `nfapi-DelayManagement-BMW` | Git branch to build. |
| `GIT_CREDENTIAL_ID` | `ming_gh_token` | Jenkins credential ID for Git access. Leave empty for public repositories. |
| `QUAY_REPO` | `bmw.ece.ntust.edu.tw/minghong` | Container registry namespace used for login, tag, and push. |
| `TAG` | `latest` | Final image tag. |
| `REGISTRY_CREDENTIAL_ID` | `ming_account` | Jenkins username/password credential ID for registry login. |
| `E2AP_VERSION` | `E2AP_V3` | E2AP version passed to the OAI RAN and FlexRIC builds. |
| `KPM_VERSION` | `KPM_V3_00` | E2SM-KPM version passed to the OAI RAN and FlexRIC builds. |

Supported E2AP values are `E2AP_V1`, `E2AP_V2`, and `E2AP_V3`.

Supported KPM values are `KPM_V2_03` and `KPM_V3_00`.

## Pipeline Stages

### Clone Repository

Checks out the selected OAI branch, initializes submodules recursively, and resets submodules to a clean state.

### Build Base Image

Builds the base image from:

```text
docker/Dockerfile.base.ubuntu
```

The resulting local image tag is:

```text
ran-base
```

### Build Build Image

Builds the FHI 7.2 build image from:

```text
docker/Dockerfile.build.fhi72.ubuntu
```

The resulting local image tag is:

```text
ran-build-fhi72
```

This stage creates a temporary patched Containerfile before calling `podman build`. The patch adds `ARG E2AP_VERSION` and `ARG KPM_VERSION` to the second Docker build stage, then passes the Jenkins parameter values with `--build-arg`.

This is required because Docker/Podman `ARG` scope does not automatically carry across `FROM` boundaries. Without redeclaring these arguments in the `ran-build-fhi72` stage, CMake receives empty values such as:

```text
-DKPM_VERSION= -DE2AP_VERSION=
```

That causes the OAI E2 CMake configuration to fail with:

```text
E2AP Unknown version selected
```

### Build gNB Image

Builds the final gNB image from:

```text
docker/Dockerfile.gNB.fhi72.ubuntu
```

The resulting local image tag is:

```text
oai-gnb
```

### Push Image

Logs in to the configured registry, tags the final image, and pushes:

```text
<QUAY_REPO>/oai-gnb:<TAG>
```

## Version Guidance

OAI RAN and FlexRIC must be built with matching `E2AP_VERSION` and `KPM_VERSION` values.

Use the defaults unless the target nearRT-RIC deployment requires a different E2AP or E2SM-KPM version:

```text
E2AP_VERSION=E2AP_V3
KPM_VERSION=KPM_V3_00
```

For OAI upstream defaults, use:

```text
E2AP_VERSION=E2AP_V2
KPM_VERSION=KPM_V2_03
```

## Troubleshooting

If the build fails during CMake configuration, check the Jenkins log for the generated `cmake` command. The E2 arguments must not be empty:

```text
-DKPM_VERSION=<value> -DE2AP_VERSION=<value>
```

If registry push fails, verify:

- `QUAY_REPO` points to the correct registry namespace.
- `REGISTRY_CREDENTIAL_ID` exists and has push permission.
- The Jenkins agent can reach the registry.

If Git checkout fails, verify:

- `GIT_REPO` and `GIT_BRANCH` are correct.
- `GIT_CREDENTIAL_ID` exists, unless the repository is public.
- The Jenkins agent can reach the Git server.
