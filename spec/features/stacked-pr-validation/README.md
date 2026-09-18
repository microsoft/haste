# Reliable pull-request validation and artifacts

**Status:** implemented

Run the existing validation workflows when a pull request targets another
feature branch, not only the default branch. Stacked fixes must not lose
wheel, image, configuration, dependency, or security checks when retargeted.

The build prerequisite also carries the published imagery-base/ACR fixes
and build-identity-based RC publication. Deployable candidates require one
verified wheel and both matching worker images, not merely green PR checks.

## Documents

- [Design](design.md)
- [Story and ownership](user-stories.md)
- [Execution and verification](plan.md)
