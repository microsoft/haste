// Copyright (c) Microsoft Corporation. All rights reserved.
// Licensed under the MIT License.

import { toBrowserStorageUrl } from "./blobUrl";

export function imageLayerThumbnail(imageLayer) {
  const previewUrl =
    imageLayer?.status === "Processed"
      ? imageLayer.postEventPreviewUrls?.find(Boolean)
      : null;
  return previewUrl ? toBrowserStorageUrl(previewUrl) : null;
}
