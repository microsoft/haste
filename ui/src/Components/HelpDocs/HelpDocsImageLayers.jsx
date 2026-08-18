// Copyright (c) Microsoft Corporation. All rights reserved.
// Licensed under the MIT License.
import createANewImageLayerVideo from '../../assets/helpDocs/imageLayers/image-layers-create-a-new-layer.mp4';
import editAnImageLayerVideo from '../../assets/helpDocs/imageLayers/image-layers-edit-a-layer.mp4';
import deleteAnImageLayerVideo from '../../assets/helpDocs/imageLayers/image-layers-delete-a-layer.mp4';

import PropTypes from 'prop-types';
import { useEffect } from 'react';

const HelpDocsImageLayers = ({ anchor }) => {
  HelpDocsImageLayers.propTypes = {
    anchor: PropTypes.string,
  };

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
      <h1 className="custom-text-color">Image Layers</h1>

      <a name="what-is-an-imageLayer"></a>
      <h2 className='pt-4'>What is an Image Layer?</h2>
      <p>An image layer is the object upon which labeling, training and predictions are performed. An image layer can be a single TIFF file, or multiple TIFF files for the same geographical Area of Interest</p>
      <p>If you have multiple satellite image files for a geographical area of interest, you can upload them all together and HASTE will combine them into a single mosaic. </p>


      <h3 className='pt-4'>Sources:</h3>

      <p>There are multiple providers of satellite imagery for damage assessment, including but not limited to the following: </p>
      <ul>
        <li>Planet Disaster Data <a href="https://source.coop/planet/disasterdata" target='_blank'>https://source.coop/planet/disasterdata</a></li>
        <li>Maxar Open Data Program <a href="https://www.maxar.com/" target='_blank'>https://www.maxar.com/</a></li>
      </ul>


      <h3 className='pt-4'>Formats:</h3>

      <p>At the moment, HASTE only accepts TIFF (.tif) files as valid imagery formats.</p>

      <hr className="mt-5 pb-4" />

      <a name="create-a-new-imageLayer"></a> 
      <h2 className=''>Create a New Image Layer </h2>
      <p>To create an Image Layer, you must first create a project. Once this is done, select the desired project from the list of projects. The project details will be displayed, which includes a button called "Create Image Layer." Clicking this will take you to the Image Layer creation form. </p>

      <h3 className='pt-4'>Browse the Open Data Catalog</h3>
      <p>The <strong>Open Data Catalog</strong> is the fastest way to add public disaster imagery without finding and copying source URLs manually. On the Create Image Layer form, select <strong>Browse Open Data Catalog</strong>, then:</p>
      <ol>
        <li>Select a disaster event.</li>
        <li>Filter scenes by provider (<strong>Vantor</strong> or <strong>Planet</strong>) and phase (<strong>Pre</strong> or <strong>Post</strong>).</li>
        <li>Select a scene to preview its footprint and imagery on the map. The scene details include capture time, sensor, ground sample distance (GSD), cloud cover, off-nadir angle, sun elevation, and file size when the provider supplies them.</li>
        <li>Optionally select <strong>Set clip area</strong> and draw a box on the map. HASTE applies this area to both pre- and post-event mosaics during processing. You can also filter the catalog to scenes that overlap the clip area. If you skip this step, HASTE processes the full scene. For large scenes, selecting a smaller area can reduce processing time and output size.</li>
        <li>Select <strong>+ Pre-event</strong> or <strong>+ Post-event</strong> to add the scene to the corresponding imagery section.</li>
      </ol>
      <p>Adding a catalog scene also fills in that section&apos;s imagery capture date and source type when the catalog provides them. Review the populated values before creating the layer, especially when combining multiple scenes.</p>
      <p>The catalog currently browses the Vantor Open Data Program (formerly Maxar) and Planet Disaster Data. You can still add imagery manually by URL or file upload when the scene you need is not available in the catalog.</p>

      <p>Add imagery files by providing publicly accessible URLs or uploading files from a local directory that show the Area of Interest (AOI). You can also combine files from both a URL and a local directory. If multiple files are provided in a section, they will be merged into a single GeoTIFF image; therefore, all files in each section must correspond to the same AOI. All files must be valid GeoTIFF (.tif) files. </p>

      <video src={createANewImageLayerVideo} controls className='w-100 mt-5 mb-3 help-docs-video-wrapper'>
        Your browser does not support the video tag.
      </video>

      <hr className="mt-5 pb-4" />

      <a name="edit-an-imageLayer"></a>
      <h2 className=''>Edit an Image Layer </h2>
      <p>You can update the name and description for an image layer after it was created from the Projects page. </p>


      <video src={editAnImageLayerVideo} controls className='w-100 mt-5 mb-3 help-docs-video-wrapper'>
        Your browser does not support the video tag.
      </video>

      <hr className="mt-5 pb-4" />

      <a name="delete-an-imageLayer"></a>
      <h2 className=''>Delete an Image Layer </h2>
      <p>You can delete an image layer using the ellipse menu on the Projects page.</p>
      <p>Deleting an image layer also deletes all its artifacts such as labels, model training checkpoints and predictions </p>

      <video src={deleteAnImageLayerVideo} controls className='w-100 mt-5 mb-3 help-docs-video-wrapper'>
        Your browser does not support the video tag.
      </video>

    </>
  );
};

export default HelpDocsImageLayers;
