// Copyright (c) Microsoft Corporation. All rights reserved.
// Licensed under the MIT License.
import PropTypes from 'prop-types';
import { useEffect } from 'react';

import createANewProjectVideo from '../../assets/helpDocs/projects/projects-create-a-new-project.mp4';
import editAProjectVideo from '../../assets/helpDocs/projects/projects-edit-a-project.mp4';
import deleteAProjectVideo from '../../assets/helpDocs/projects/projects-delete-a-project.mp4';

const HelpDocsProjects = ({ anchor }) => {
  HelpDocsProjects.propTypes = {
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
      <h1 className="custom-text-color">Projects</h1>

      <a name="what-is-a-project"></a>
      <h2 className='pt-4'>What is a Project?</h2>
      <p>A project is a way to organize image layers and damage assessments conducted on them. It is a collection of imagery files, labels, training checkpoints and inference results in various formats.<br />
        For e.g., you can create a new project per disaster event </p>

      <hr className="mt-5 pb-4" />

      <a name="create-a-new-project"></a>
      <h2 className='pt-4'>Create a new Project</h2>

      <p>Project creation requires the following information:</p>
      <ol>
        <li>Name – any suitable name for the project </li>
        <li>Description -any additional information about the project </li>
        <li>Event Date – date that the disaster occurred. This date is stored for informational purposes and does not affect any processing</li>
        <li>Affected Countries – from the dropdown, select the country (or multiple countries) that were affected by the disaster. This data is stored for informational purposes and does not affect any downstream processing</li>
        <li>Primary Classes – these are the classes of labels that you will add to an image layer to help train the model.</li>
      </ol>

      <p>The classes of labels that the model needs to be trained on are:</p>
      <ul>
        <li>Background</li>
        <li>Buildings</li>
        <li>Damaged Building</li>
      </ul>
      <p>These classes are provided by default on the project creation form. You can keep the default colors or change them to suit your need.</p>

      <video src={createANewProjectVideo} controls className='w-100 mt-5 mb-3 help-docs-video-wrapper'>
        Your browser does not support the video tag.
      </video>


      <hr className="mt-5 pb-4" />

      <a name="edit-a-project"></a>
      <h2 className='pt-4'>Edit a Project</h2>

      <p>You can update the name and description for a project after it was created from the Projects page.


      <video src={editAProjectVideo} controls className='w-100 mt-5 mb-3 help-docs-video-wrapper'>
        Your browser does not support the video tag.
      </video>

      </p>

      <hr className="mt-5 pb-4" />

      <a name="delete-a-project"></a>
      <h2 className='pt-4'>Delete a Project</h2>

      <p>You can delete a project using the ellipse menu on the Projects page. Deleting a project will delete all associated artifacts such as image layers, labels and training results.

      <video src={deleteAProjectVideo} controls className='w-100 mt-5 mb-3 help-docs-video-wrapper'>
        Your browser does not support the video tag.
      </video>

      </p>
    </>
  );
};

export default HelpDocsProjects;
