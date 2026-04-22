// Copyright (c) Microsoft Corporation. All rights reserved.
// Licensed under the MIT License.
import PropTypes from 'prop-types';
import { useEffect } from 'react';
import HelpDocsOverviewBubble from './HelpDocsOverviewBubble';
import endToEndExampleVideo from '../../assets/helpDocs/overview/overview-end-to-end-example.mp4';


const HelpDocsOverview = ({ anchor, setCurrentHelpDocSection }) => {
  // PropTypes for the component
  HelpDocsOverview.propTypes = {
    anchor: PropTypes.string,
    setCurrentHelpDocSection: PropTypes.func
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
      <h1 className="custom-text-color">Overview</h1>

      <a name="introduction"></a>
      <h2 className='pt-4'></h2>

      <p><strong>HASTE</strong>, or High-speed Assessment and Satellite Tracking for Emergencies, is an AI-powered tool designed by the <strong>Microsoft AI for Good Lab</strong> to quickly identify and evaluate structural damage to buildings after a catastrophe.</p>
      <p>Leveraging advanced image analysis and machine learning, it empowers emergency responders and authorities to prioritize critical areas, accelerate recovery efforts, and enhance safety assessments.</p>
      <p>The basic workflow is to add imagery to a project, label a small area of the imagery with some classification labels and use this to train the model. The model will apply these learnings to generate damage predictions across the entire imagery. </p>

      <video src={endToEndExampleVideo} controls className='w-100 mt-5 mb-3 help-docs-video-wrapper'>
        Your browser does not support the video tag.
      </video>

      <hr className="mt-5 pb-4" />

      <div className="col-12 d-flex flex-column flex-xxl-row gap-4 pt-4 pb-5">
        <HelpDocsOverviewBubble
          iconName="FolderHorizontal"
          title="Projects"
          text="A collection of image layers and damage assessments conducted on them"
          link="projects"
          setCurrentHelpDocSection={setCurrentHelpDocSection}
          style={bubbleStyle}
        />
        <HelpDocsOverviewBubble
          iconName="FileImage"
          title="Image Layers"
          text="Satellite imagery files for areas of interest"
          link="imageLayers"
          setCurrentHelpDocSection={setCurrentHelpDocSection}
          style={bubbleStyle}
        />
        <HelpDocsOverviewBubble
          iconName="Edit"
          title="Labeling"
          text="Annotate satellite imagery to train the model"
          link="labeling"
          setCurrentHelpDocSection={setCurrentHelpDocSection}
          style={bubbleStyle}
        />
        <HelpDocsOverviewBubble
          iconName="ModelingView"
          title="Model Training"
          text="Train a model to predict damage across the entire imagery"
          link="modelTraining"
          setCurrentHelpDocSection={setCurrentHelpDocSection}
          style={bubbleStyle}
        />
        <HelpDocsOverviewBubble
          iconName="ReleaseDefinition"
          title="Results"
          text="View the results of the model predictions and download them in various formats"
          link="results"
          setCurrentHelpDocSection={setCurrentHelpDocSection}
          style={bubbleStyle}
        />
      </div>
    </>
  );
};


export default HelpDocsOverview;
