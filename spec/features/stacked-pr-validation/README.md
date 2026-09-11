# Stacked pull-request validation

**Status:** implemented

Run the existing validation workflows when a pull request targets another
feature branch, not only the default branch. Stacked fixes must not lose
wheel, image, configuration, dependency, or security checks when retargeted.

## Documents

- [Design](design.md)
- [Story and ownership](user-stories.md)
- [Execution and verification](plan.md)
