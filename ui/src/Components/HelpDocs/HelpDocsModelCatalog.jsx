// Copyright (c) Microsoft Corporation. All rights reserved.
// Licensed under the MIT License.
import PropTypes from 'prop-types';
import { useEffect } from 'react';


import addModelsToCatalogImage from '../../assets/helpDocs/modelCatalog/model-catalog-add-models-to-catalog.jpg';
import useModelCatalogImage from '../../assets/helpDocs/modelCatalog/model-catalog-use-model-catalog.jpg';
import removeAModelFromCatalogImage from '../../assets/helpDocs/modelCatalog/model-catalog-remove-a-model-from-model-catalog.jpg';

const HelpDocsModelCatalog = ({ anchor }) => {
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



      <h1 className="custom-text-color">Model Catalog</h1>

      <a name="introduction"></a>
      <h2 className='pt-4'></h2>

      <p>
        The Model Catalog is a centralized registry of base models available for training. It provides a collection of pre-trained models, each tailored to specific project types and imagery sources, that serve as the foundation for fine-tuning with your own labeled data.</p>



      <hr className="mt-5" />

      <a name="add-a-model-to-catalog"></a>
      <h2 className='pt-4'>Add a Model to Catalog</h2>
      <p>Once a model has been trained and its inference has been fully processed, you can add it to the Model Catalog so it can be reused as a base model in future training runs. Follow the steps below:</p>

      <p>
        <ol>
          <li><strong className='fw-semibold'>Navigate to the Models table:</strong> Go to your project page and locate the models table for the image layer whose model you want to catalog. Click on the three-dot menu icon next to the model you want to catalog. The &quot;Add Model to Catalog&quot; option will only be available for models whose inference status is &quot;Processed&quot;.

            <img src={addModelsToCatalogImage} alt="Adding Models to Catalog" loading="lazy" decoding="async" className="img-fluid mt-4 mb-2" />

          </li>
          <li><strong className='fw-semibold'>Fill in the form:</strong> A dialog will appear with the following fields:
            <ul>
              <li><strong className='fw-semibold'>Name:</strong> Provide a unique, descriptive name for the model in the catalog (max 100 characters).</li>
              <li><strong className='fw-semibold'>Description:</strong> Add a detailed description of the model, including what it was trained on and its intended use (max 2000 characters).</li>
              <li><strong className='fw-semibold'>Metadata:</strong> Optionally, add custom key-value metadata entries to tag and categorize the model. Click &quot;Add Metadata&quot; to create additional entries as needed.</li>
            </ul>
          </li>
          <li><strong className='fw-semibold'>Submit:</strong> Click the &quot;Submit&quot; button to add the model to the catalog. The model&apos;s project type and imagery source will be automatically associated, so it appears as a base model option in matching future training runs.</li>
        </ol>
      </p>


      <hr className="mt-5 pb-4" />

      <a name="use-the-model-catalog"></a>
      <h2 className='pt-4'>Use the Model Catalog (Train a New Model using a Base Model)</h2>

      <p>The Base Model is a parameter of the model training process. For a complete guide on training models, see <a href="/help-docs/modelTraining#train-a-new-model">Train a New Model</a>.
        <br />
        <img src={useModelCatalogImage} alt="Using Model Catalog" loading="lazy" decoding="async" className="img-fluid mt-4 mb-2" />

      </p>

      <hr className="mt-5 pb-4" />

      <a name="remove-a-model-from-the-catalog"></a>
      <h2 className='pt-4'>Remove a model from the Model Catalog</h2>

      <p>A model can be removed from the Model Catalog. This action does not delete the original trained model from your project — it only removes it from the shared catalog so it will no longer appear as a base model option.</p>

      <p>
        <ol>
          <li><strong className='fw-semibold'>Navigate to the Model Catalog:</strong> Open the Model Catalog page from the main navigation. You will see a table listing all cataloged models with details such as name, description, source, event type, and cataloged date.</li>
          <li><strong className='fw-semibold'>Locate the model:</strong> Use the search bar to filter models by name, description, or any other field to quickly find the model you want to remove.</li>
          <li><strong className='fw-semibold'>Open the model menu:</strong> Click on the three-dot menu icon next to the model you want to remove, then select &quot;Remove&quot;.

            <img src={removeAModelFromCatalogImage} alt="Removing a Model from Catalog" loading="lazy" decoding="async" className="img-fluid mt-4 mb-2" />

          </li>
          <li><strong className='fw-semibold'>Confirm removal:</strong> A confirmation dialog will appear asking if you want to remove the model from the catalog. Click &quot;Yes&quot; to proceed or &quot;No&quot; to cancel.</li>
          <li><strong className='fw-semibold'>Wait for completion:</strong> The application will display a loading indicator while the model is being removed. Once complete, a success message will confirm the model has been removed.</li>
        </ol>
      </p>

      <p><strong className='fw-semibold'>Important:</strong> This action requires Administrator privileges.</p>
    </>
  );
};

HelpDocsModelCatalog.propTypes = {
  anchor: PropTypes.string,
};

export default HelpDocsModelCatalog;
