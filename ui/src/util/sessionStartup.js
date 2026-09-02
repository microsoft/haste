export async function loadSession({
  validateUser,
  setAppParams,
  setIsLoading,
  setSessionError,
}) {
  setSessionError(false);
  setIsLoading(true);
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
  } finally {
    setIsLoading(false);
  }
}