export async function loadSession({
  validateUser,
  setAppParams,
  setSessionError,
}) {
  setSessionError(false);
  try {
    await validateUser(setAppParams);
    return true;
  } catch {
    setAppParams((previous) => ({
      ...previous,
      userId: null,
      identityId: null,
      userRoles: [],
      userSettings: {},
      userStatus: null,
      publishingEnabled: false,
      publishingProviders: [],
    }));
    setSessionError(true);
    return false;
  }
}