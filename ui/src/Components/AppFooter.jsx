// Copyright (c) Microsoft Corporation. All rights reserved.
// Licensed under the MIT License.

function AppFooter() {
  if (import.meta.env.VITE_SHOW_FOOTER !== 'true') return null;

  return (
    <footer className="app-footer">
      <a href="https://go.microsoft.com/fwlink/?LinkId=521839" target="_blank" rel="noopener noreferrer">
        Privacy &amp; Cookies
      </a>
      <span>&copy; Microsoft {new Date().getFullYear()}</span>
    </footer>
  );
}

export default AppFooter;
