// Copyright (c) Microsoft Corporation. All rights reserved.
// Licensed under the MIT License.
import labelingImageryProperties from '../../assets/helpDocs/labeling/labeling-imagery-properties.png';
import labelingDrawingTools from '../../assets/helpDocs/labeling/labeling-drawing-tools.png';
import labelingPrimaryClasses from '../../assets/helpDocs/labeling/labeling-primary-classes.png';
import labelingDenseClusteredLabelingCorrect from '../../assets/helpDocs/labeling/labeling-dense-clustered-labeling-correct.jpg';
import labelingDenseClusteredLabelingWrong from '../../assets/helpDocs/labeling/labeling-dense-clustered-labeling-wrong.jpg';
import labelingHighPrecisionLabelingCorrect from '../../assets/helpDocs/labeling/labeling-high-precision-labeling-correct.jpg';
import labelingHighPrecisionLabelingWrong from '../../assets/helpDocs/labeling/labeling-high-precision-labeling-wrong.jpg';
import labelingMaximizeDiversityOfLabelsHigh from '../../assets/helpDocs/labeling/labeling-maximize-diversity-of-labels-high.jpg';
import labelingMaximizeDiversityOfLabelsLow from '../../assets/helpDocs/labeling/labeling-maximize-diversity-of-labels-low.jpg';
import labelingLabelRelevantPortionsOnlyCorrect from '../../assets/helpDocs/labeling/labeling-label-relevant-portions-only-correct.jpg';
import labelingLabelRelevantPortionsOnlyWrong from '../../assets/helpDocs/labeling/labeling-label-relevant-portions-only-wrong.jpg';


import PropTypes from 'prop-types';
import { useEffect } from 'react';


const HelpDocsLabeling = ({ anchor }) => {
  // PropTypes for the component
  HelpDocsLabeling.propTypes = {
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

  const bubbleStyle = { minHeight: 100, display: 'flex', flexDirection: 'column' };

  return (
    <>
      <h1 className="custom-text-color">Labeling</h1>

      <a name="introduction"></a>
      <h2 className='pt-4'></h2>
      <p>Labeling refers to manually annotating damaged areas, undamaged areas and background areas on a sub-section of satellite imagery. These labels are what the model will use to train itself and generate damage predictions over the rest of the image. </p>
      <p>This is a required step before any model training or inference can be run. </p>

      <hr className="mt-5 pb-4" />

      <a name="labeling-tool"></a>
      <h2 className=''>Labeling Tool</h2>

      <h3 className='pt-4'>Launching the labeling tool</h3>

      <p>To launch the labeling tool, go to the Projects page and click on “Launch” button next to the image layer that you wish to run assessment on. </p>

      <h3 className='pt-4'>Imagery Properties:</h3>

      <div className='row col-12 pt-4 pb-4'>
        <div className="col-12 d-flex flex-column flex-lg-row align-items-start justify-content-start mb-3 mb-lg-0">
          <img src={labelingImageryProperties} alt="Labeling Imagery Properties" className="img-fluid pe-lg-5" />
          <div>
            <p className='mt-4 mt-lg-0'>
              This panel allows you to adjust the visual properties of the pre and post imagery to improve clarity or highlight specific features. The available controls are:
            </p>
            <ul>
              <li><b>Opacity:</b> Adjusts the transparency of the map layer. Slide left to make the layer more transparent; right to make it more opaque.</li>
              <li><b>Contrast:</b> Changes the difference between light and dark areas in the image. Increasing contrast can make features stand out more clearly.</li>
              <li><b>Hue Rotation:</b> Rotates the color spectrum of the image. Useful for visually distinguishing features when natural colors are not sufficient.</li>
              <li><b>Saturation:</b> Controls the intensity of colors. Lower saturation results in more grayscale images; higher saturation produces more vivid colors.</li>
              <li><b>Reset Controls:</b> Resets all sliders to their default values.</li>
            </ul>
            <p className='mt-4 mt-lg-0'>
              <b>Imagery toggle:</b> Click on the toggle to switch between post event and pre event imagery. If you did not upload pre event imagery, the tool will default to Azure Basemap. You can also use the keyboard shortcut - Ctrl+Alt+c
              <br /><br />
              Use these controls to optimize the map view for your labeling tasks or analysis needs.
            </p>
          </div>
        </div>
      </div>

      <h3 className='pt-4'>Drawing Tools</h3>

      <img src={labelingDrawingTools} alt="Labeling Drawing Tools" className="img-fluid pe-5 pt-4 pb-4" />

      <p>
        Use these tools to create and manage geometric annotations on the map. Each button allows you to switch between interaction modes:
      </p>

      <ul>
        <li><strong>Pan Tool (Hand icon):</strong> Enables map navigation. Use this mode to move the map without editing any features.</li>
        <li><strong>Polygon Tool (Hexagon icon):</strong> Draw custom polygons by clicking multiple points on the map. Useful for irregular areas.</li>
        <li><strong>Rectangle Tool (Square icon):</strong> Draw rectangular shapes by clicking and dragging.</li>
        <li><strong>Circle Tool (Circle icon):</strong> Draw circular shapes by clicking and dragging from the center outward.</li>
        <li><strong>Edit Tool (Pencil icon):</strong> Select and modify existing shapes. You can move vertices or reshape the geometry.</li>
        <li><strong>Delete Tool (Trash icon):</strong> Remove selected annotations from the map.</li>
      </ul>

      <h3 className='pt-4'>Switching between label classes</h3>

      <div className='row col-12 pt-4'>
        <div className="col-12 d-flex flex-column flex-lg-row align-items-start justify-content-start mb-3 mb-lg-0">
          <img src={labelingPrimaryClasses} alt="Labeling Primary Classes" className="img-fluid pe-sm-5" />
          <p className='pt-3 pt-lg-0'>
            Switch between label classes here. You must select a tool as well as a class to draw a label.
          </p>
        </div>
      </div>

      <h3 className='pt-4'>Saving Labels</h3>
      <p>Click on "Save" to save all labels drawn so far. Alternatively, click on the down arrow next to "Save" to save labels and initiate model training in one click.</p>

      <hr className="mt-5 pb-4" />

      <a name="tips-for-effective-labeling"></a>
      <h2 className=''>Tips for Effective Labeling</h2>

      <h3 className='pt-4'>Minimum number of labels</h3>
      <p>Draw at minimum 5-10 labels for each class. Model training gets more effective with more quantity and quality of labels. 70-100 make for a good training set. More than a 150 labels are not necessary. </p>

      <h3 className='pt-4'>Cluster labels closely</h3>
      <p>Label features that are directly adjacent to each other. For example, if you are labeling a building, then label the background area around it as well. This is important because unlabeled areas are not used in training the model, therefore if you label a building, but do not label around it, then model will not be penalized for making a large blurry prediction around the building (vs. a precise prediction that follows the lines of the building). The following images illustrate a good and bad example of dense clustered labeling:</p>

      <div className="row">
        <div className="col-12 col-xl-6">
          <img src={labelingDenseClusteredLabelingCorrect} alt="Dense Clustered labeling correct" className="w-100 pt-4 pb-4" />
        </div>
        <div className="col-12 col-xl-6">
          <img src={labelingDenseClusteredLabelingWrong} alt="Dense Clustered labeling wrong" className="w-100 pt-4 pb-4" />
        </div>
      </div>

      <h3 className='pt-4'>Draw labels precisely</h3>

      <p>Labeling features with high precision is more important than rapidly labeling large areas with low precision​. Following images illustrate a good and bad example of high precision labeling:</p>
      <div className="row">
        <div className="col-12 col-xl-6">
          <img src={labelingHighPrecisionLabelingCorrect} alt="High Precision Labeling correct" className="w-100 pt-4 pb-4" />
        </div>
        <div className="col-12 col-xl-6">
          <img src={labelingHighPrecisionLabelingWrong} alt="High Precision Labeling wrong" className="w-100 pt-4 pb-4" />
        </div>
      </div>

      <h3 className='pt-4'>Maximize label diversity</h3>

      <p>Label diverse features. For example, labeling 20 identical looking buildings is less useful to the model training as opposed labelling 20 buildings with varying roof colors, sizes and textures. Following images illustrate a example high and low diversity of labels:</p>
      <div className="row">
        <div className="col-12 col-xl-6">
          <img src={labelingMaximizeDiversityOfLabelsHigh} alt="Maximize Diversity of Labels high" className="w-100 pt-4 pb-4" />
        </div>
        <div className="col-12 col-xl-6">
          <img src={labelingMaximizeDiversityOfLabelsLow} alt="Maximize Diversity of Labels low" className="w-100 pt-4 pb-4" />
        </div>
      </div>

      <h3 className='pt-4'>Label relevant portions only</h3>

      <p>Buildings can have mixed labels e.g. a partially damaged building will have some pixels represented the damaged class while other pixels will not. When labelling, only assign the damaged pixels to the damaged class as opposed to the whole building. Next images ilustrate a good and bad example of labeling relevant portions:</p>
      <div className="row">
        <div className="col-12 col-xl-6">
          <img src={labelingLabelRelevantPortionsOnlyCorrect} alt="Label Relevant Portions Only correct" className="w-100 pt-4 pb-4" />
        </div>
        <div className="col-12 col-xl-6">
          <img src={labelingLabelRelevantPortionsOnlyWrong} alt="Label Relevant Portions Only wrong" className="w-100 pt-4 pb-4" />
        </div>
      </div>
    </>
  );
};


export default HelpDocsLabeling;
