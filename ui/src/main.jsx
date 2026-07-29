// Copyright (c) Microsoft Corporation. All rights reserved.
// Licensed under the MIT License.
import ReactDOM from 'react-dom/client';
import { BrowserRouter } from 'react-router-dom';
import App from './App';
import 'bootstrap/dist/css/bootstrap.min.css';

import { AppProvider } from "./AppContext.jsx";
import { ThemeProvider } from "./util/ThemeContext.jsx";
import { getInitialTheme, applyTheme } from "./util/theme";
import { getInitialPalette, applyPaletteCssVars } from "./util/theme";

// Apply the persisted theme + palette before first render to avoid a flash.
applyTheme(getInitialTheme());
applyPaletteCssVars(getInitialPalette());

ReactDOM.createRoot(document.getElementById('root')).render(
  <BrowserRouter>
    <ThemeProvider>
      <AppProvider>
        <App />
      </AppProvider>
    </ThemeProvider>
  </BrowserRouter>
);