// Copyright (c) Microsoft Corporation. All rights reserved.
// Licensed under the MIT License.
import resultsDownloadGeopackageImage from '../../assets/helpDocs/results/results-download-geopackage.png';
import resultsDownloadAllArtifactsImage from '../../assets/helpDocs/results/results-download-all-artifacts.png';
import resultsVisualizerImage from '../../assets/helpDocs/results/results-visualizer.png';

import PropTypes from 'prop-types';
import { useEffect } from 'react';

const HelpDocsResults = ({ anchor }) => {
  useEffect(() => {
    if (anchor) {
      const element = document.getElementsByName(anchor)[0];
      if (element) {
        element.scrollIntoView({ behavior: "smooth", block: "start" });
      }
    } else {
      window.scrollTo(0, 0);
    }
  }, [anchor]);

  return (

    <>



      <h1 className="custom-text-color">Results</h1>

      <a name="introduction"></a>
      <h2 className='pt-4'></h2>
      <p>HASTE generates various types of damage assessment results. They are explained in detail in the sections that follow. </p>

      <hr className="mt-5 pb-4" />

      <a name="built-in-visualizer"></a>
      <h2 className=''>Built-in Visualizer</h2>

      <p>This opens a damage visualizer tool within HASTE. This is useful for quickly visualizing damage predictions, comparing them with pre-event imagery and for sharing these results via screenshots </p>
      <p>
        Use <kbd>A</kbd>, <kbd>S</kbd>, and <kbd>D</kbd> to move the imagery
        swipe divider left, to an even split, or right.
      </p>

      <img src={resultsVisualizerImage} alt="Visualizer" loading="lazy" decoding="async" className="img-fluid pe-5 pt-4 pb-4" />

      <hr className="mt-5 pb-4" />

      <a name="downloadable-artifacts"></a>
      <h2 className=''>Downloadable Artifacts</h2>
      <h3 className='pt-4'>Predictions as a geopackage</h3>
      <p>The predicted damage layer is downloadable as a geopackage file (.gpkg) that can then be integrated into other geospatial visualization tools, such as ArcGIS, QGIS, etc.</p>

      <img src={resultsDownloadGeopackageImage} alt="Download Geopackage" loading="lazy" decoding="async" className="img-fluid pe-5 pt-4 pb-4" />



      <h3 className='pt-4'>Intermediate Outputs</h3>
      <p>All intermediate outputs, such as the saved labels, training checkpoint files, downloaded  building footprints and predictions can be downloaded as a zip file. This is useful for troubleshooting training failures. </p>

      <img src={resultsDownloadAllArtifactsImage} alt="Download all artifacts" loading="lazy" decoding="async" className="img-fluid pe-5 pt-4 pb-4" />

    </>
  );
};

HelpDocsResults.propTypes = {
  anchor: PropTypes.string,
};

export default HelpDocsResults;
