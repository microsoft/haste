# Rollout: Keyless storage

1. Validate candidate artifacts and code; record exact source and digests.
2. With explicit approval, apply prerequisite identity grants and deploy through
   the GitHub Actions dev1 candidate path. Do not use direct registry builds.
   Drain in-flight multipart uploads from the old local-staging implementation.
3. Validate all workflows without the Blob connection string. Separately verify
   scratch persistence, instance changes and actual removal of the old mount.
4. After review and acceptance, merge and promote verified main artifacts:
   dev1, then dev2, then production, with approval for each live stage.
5. After legacy-client checks, separately approve policy retirement and
   per-account Shared Key disablement. Retained File accounts require their own
   consumer audit. Do not change unrelated auto-storage.
6. Verify positive identity/delegation and negative Shared Key requests and
   confirm redeployment does not restore credentials, mounts or permissive flags.

Apply the new container-scoped Contributor and account Delegator assignments
before retiring old account-level Blob Owner grants. Incremental Bicep does not
delete omitted role assignments. Enumerate the shared identity's grants on the
application and retained File accounts; after validating replacements, remove
only the reviewed legacy Owner assignments by their exact IDs.

The compatibility parameters `allowMainSharedKeyAccess` and
`allowFileSharedKeyAccess` default to true until the respective live gates pass.
Persist approved false values in each environment's IaC parameter source before
reapplying infrastructure. Application-only deploys neither apply these account
flags nor create prerequisite RBAC grants.

Before each stage, capture nonsecret package/image/config/role rollback metadata.
Never copy account keys into public docs or session artifacts. Retain File data.
Restoring key-dependent code after disablement requires explicit authorization
to temporarily re-enable Shared Key. Policy revocation is not undone by a code
rollback; issue fresh delegation tokens instead.
