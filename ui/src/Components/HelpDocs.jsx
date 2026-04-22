// Copyright (c) Microsoft Corporation. All rights reserved.
// Licensed under the MIT License.
import { useContext, useEffect, useState } from "react";
import { AppContext } from "../AppContext";
import HelpDocsNav from "./HelpDocs/HelpDocsNav.jsx";

import HelpDocsOverview from "./HelpDocs/HelpDocsOverview.jsx";
import HelpDocsProjects from "./HelpDocs/HelpDocsProjects.jsx";
import HelpDocsImageLayers from "./HelpDocs/HelpDocsImageLayers.jsx";
import HelpDocsLabeling from "./HelpDocs/HelpDocsLabeling.jsx";
import HelpDocsModelTraining from "./HelpDocs/HelpDocsModelTraining.jsx";
import HelpDocsResults from "./HelpDocs/HelpDocsResults.jsx";
import HelpDocsModelCatalog from "./HelpDocs/HelpDocsModelCatalog.jsx";

import { useNavigate } from "react-router-dom";

const HelpDocs = () => {

  const { setIsLoading, setAppParams } = useContext(AppContext);
  const [currentHelpDocSection, setCurrentHelpDocSection] = useState(() => {
    // Get the section from the URL path and hash
    let path = window.location.pathname.replace(/^\/help-docs\/?/, "");
    const hash = window.location.hash ? window.location.hash.substring(1) : "";
    // If path is empty (i.e., just /help-docs or /help-docs/), default to "overview"
    if (!path) {
      return "overview";
    }
    if (hash) {
      return `${path}#${hash}`;
    }
    return path;
  });

  useEffect(() => {
    setAppParams((prevParams) => ({
      ...prevParams,
      appTitle: "HASTE Docs",
    }));
    setIsLoading(false);
  }, []);

  useEffect(() => {
    setSelectedKey(currentHelpDocSection.replace('#', '-'));
  }, [currentHelpDocSection]);

  const navLinkGroups = [
    {
      links: [
        {
          key: 'overview',
          name: 'Overview',
          expandAriaLabel: 'Workflow',
          links: [
            {
              key: 'overview-introduction',
              name: 'Introduction',
              onClick: () => setCurrentHelpDocSection('overview#introduction'),
            }
          ]
        },
        {
          key: 'projects',
          name: 'Projects',
          expandAriaLabel: 'Projects',
          links: [
            {
              key: 'projects-what-is-a-project',
              name: 'What is a Project?',
              onClick: () => setCurrentHelpDocSection('projects#what-is-a-project'),
            },
            {
              key: 'projects-create-a-new-project',
              name: 'Create a New Project',
              onClick: () => setCurrentHelpDocSection('projects#create-a-new-project'),
            },
            {
              key: 'projects-edit-a-project',
              name: 'Edit a Project',
              onClick: () => setCurrentHelpDocSection('projects#edit-a-project'),
            },
            {
              key: 'projects-delete-a-project',
              name: 'Delete a Project',
              onClick: () => setCurrentHelpDocSection('projects#delete-a-project'),
            }
          ],
        },
        {
          key: 'imageLayers',
          name: 'Image Layers',
          expandAriaLabel: 'Image Layers',
          links: [
            {
              key: 'imageLayers-what-is-an-imageLayer',
              name: 'What is an Image Layer?',
              onClick: () => setCurrentHelpDocSection('imageLayers#what-is-an-imageLayer'),
            },
            {
              key: 'imageLayers-create-a-new-imageLayer',
              name: 'Create a New Image Layer',
              onClick: () => setCurrentHelpDocSection('imageLayers#create-a-new-imageLayer'),
            },
            {
              key: 'imageLayers-edit-an-imageLayer',
              name: 'Edit an Image Layer',
              onClick: () => setCurrentHelpDocSection('imageLayers#edit-an-imageLayer'),
            },
            {
              key: 'imageLayers-delete-an-imageLayer',
              name: 'Delete an Image Layer',
              onClick: () => setCurrentHelpDocSection('imageLayers#delete-an-imageLayer'),
            },
          ],
        },
        {
          key: 'labeling',
          name: 'Labeling',
          expandAriaLabel: 'Labeling',
          links: [
            {
              key: 'labeling-introduction',
              name: 'Introduction',
              onClick: () => setCurrentHelpDocSection('labeling#introduction'),
            },
            {
              key: 'labeling-labeling-tool',
              name: 'Labeling Tool',
              onClick: () => setCurrentHelpDocSection('labeling#labeling-tool'),
            },
            {
              key: 'labeling-tips-for-effective-labeling',
              name: 'Tips for Effective Labeling ',
              onClick: () => setCurrentHelpDocSection('labeling#tips-for-effective-labeling'),
            }
          ],
        },
        {
          key: 'modelTraining',
          name: 'Model Training and Inference',
          expandAriaLabel: 'Model Training',
          links: [
            {
              key: 'modelTraining-introduction',
              name: 'Introduction',
              onClick: () => setCurrentHelpDocSection('modelTraining#introduction'),
            },

            {
              key: 'modelTraining-train-a-new-model',
              name: 'Train a New Model',
              onClick: () => setCurrentHelpDocSection('modelTraining#train-a-new-model'),
            }
          ]
        },
        {
          key: 'results',
          name: 'Results',
          expandAriaLabel: 'Results',
          links: [
            {
              key: 'results-introduction',
              name: 'Introduction',
              onClick: () => setCurrentHelpDocSection('results#introduction'),
            },
            {
              key: 'results-built-in-visualizer',
              name: 'Built-in Visualizer',
              onClick: () => setCurrentHelpDocSection('results#built-in-visualizer'),
            },
            {
              key: 'results-downloadable-artifacts',
              name: 'Downloadable Artifacts',
              onClick: () => setCurrentHelpDocSection('results#downloadable-artifacts'),
            }
          ]
        },
        {
          key: 'modelCatalog',
          name: 'Model Catalog',
          expandAriaLabel: 'Model Catalog',
          links: [
            {
              key: 'modelCatalog-introduction',
              name: 'Introduction',
              onClick: () => setCurrentHelpDocSection('modelCatalog#introduction'),
            },

            {
              key: 'modelCatalog-add-a-model-to-catalog',
              name: 'Add a Model to Catalog',
              onClick: () => setCurrentHelpDocSection('modelCatalog#add-a-model-to-catalog'),
            },
            {
              key : 'modelCatalog-use-the-model-catalog',
              name: 'Use the Model Catalog',
              onClick: () => setCurrentHelpDocSection('modelCatalog#use-the-model-catalog'),
            },
            {
              key : 'modelCatalog-remove-a-model-from-the-catalog',
              name: 'Remove a Model from Catalog',
              onClick: () => setCurrentHelpDocSection('modelCatalog#remove-a-model-from-the-catalog'),
            },
          ]
        },
      ]
    }
  ];

  const [selectedKey, setSelectedKey] = useState(navLinkGroups[0].links[0].key);


  const navigate = useNavigate();

  function getCurrentHelpDocSection() {

    const section = currentHelpDocSection ? currentHelpDocSection.split("#")[0] : "overview";
    const anchor = currentHelpDocSection ? currentHelpDocSection.split("#")[1] : null;

    // Update the URL when currentHelpDocSection changes
    useEffect(() => {
      if (currentHelpDocSection) {
        navigate(`/help-docs/${currentHelpDocSection}`);
      } else {
        navigate(`/help-docs/overview`);
      }
      // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [currentHelpDocSection]);

    switch (section) {
      case "overview":
        return <HelpDocsOverview anchor={anchor} setCurrentHelpDocSection={setCurrentHelpDocSection} />;
      case "projects":
        return <HelpDocsProjects anchor={anchor} />;
      case "imageLayers":
        return <HelpDocsImageLayers anchor={anchor} />;
      case "labeling":
        return <HelpDocsLabeling anchor={anchor} />
      case "modelTraining":
        return <HelpDocsModelTraining anchor={anchor} />;
      case "results":
        return <HelpDocsResults anchor={anchor} />;
      case "modelCatalog":
        return <HelpDocsModelCatalog anchor={anchor} />;  
      default:
        return <HelpDocsOverview anchor={anchor} />;
    }
  }

  return (
    <div className="d-flex flex-grow-1 flex-column flex-lg-row container-fluid pt-2 help-docs">

      {/* Left Navigation */}
      <HelpDocsNav
        helpSections={navLinkGroups}
        selectedKey={selectedKey}
      />

      {/* Main Content */}
      <div className="d-flex flex-grow-1 flex-column p-3 p-lg-5 col-lg-5 help-docs-content-container">
        <div className="col-12 col-xl-10 col-xxl-10">
          {getCurrentHelpDocSection()}
        </div>
      </div>
    </div>
  );
};

export default HelpDocs;
