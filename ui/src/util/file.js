// Copyright (c) Microsoft Corporation. All rights reserved.
// Licensed under the MIT License.
export function fileDownload(url, setDialog) {
    if (url !== undefined) {
        try {
            // Add a cache-busting query parameter to force download and ignore cache
            const separator = url.includes('?') ? '&' : '?';
            const cacheBustedUrl = `${url}${separator}_=${Date.now()}`;
            // Open the file in a new tab
            window.open(cacheBustedUrl, '_blank', 'noopener,noreferrer');
        } catch (error) {
            setDialog("Important", `An error occurred while downloading the file. Please try again later.`, [
                {
                    type: "primary",
                    key: "close",
                    text: "Close",
                    onClick: () => setDialog(),
                }
            ]);
        }
    } else {
        setDialog("Important", `An error occurred while downloading the file. Please try again later.`, [
            {
                type: "primary",
                key: "close",
                text: "Close",
                onClick: () => setDialog(),
            }
        ]);
    }
}
