// Copyright (c) Microsoft Corporation. All rights reserved.
// Licensed under the MIT License.
import PropTypes from 'prop-types';
import { useEffect } from 'react';

import saveAndTrainModelImage from '../../assets/helpDocs/model/model-save-and-train.png';
import trainModelImage from '../../assets/helpDocs/model/model-train.png';

const HelpDocsModelTraining = ({ anchor }) => {
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



      <h1 className="custom-text-color">Model Training</h1>

      <a name="introduction"></a>
      <h2 className='pt-4'></h2>
      <p>There is generally a large amount of variation in satellite imagery from one geographical region to the next and training results can rarely be applied from one region to the next without a lot of re-training.</p>
      <p>To ensure good quality results, HASTE works by training the model afresh in each training run. </p>

      <hr className="mt-5 pb-4" />

      <a name="train-a-new-model"></a>
      <h2 className='pt-4'>Train a new model</h2>

      <p>Training a model requires that a minimum amount of manual labeling be done on the image layer. Refer to previous sections for tips on effective labeling. </p>
      <p>Once you have created labels, you can train a model in two ways:</p>

      <p>
        <ol>
          <li>by clicking on “Save and Train” in the labeling tool itself<br />
            <img src={saveAndTrainModelImage} alt="Save and Train Model" loading="lazy" decoding="async" className="img-fluid mt-4 mb-4" />
          </li>
          <li>OR by clicking on the Train button for that image layer on the Projects page<br />
            <img src={trainModelImage} alt="Train Model" loading="lazy" decoding="async" className="img-fluid mt-4 mb-4" />
          </li>
        </ol>

        <h3 className='pt-4'>Model Training parameters</h3>
        <p>Various parameters can be changed to train the model with fine grained control. If you’re not sure what values to use, leave them at their default values.</p>
        <ul>
          <li><strong>Model Name:</strong> A unique name for your model.</li>
          <li><strong>Base Model:</strong> The base model from the model catalog that will be fine-tuned with your data. Only models whose project event type and image layer source match your project and image layer are shown. Will be disabled if no matching models are available.</li>
          <li><strong>Learning Rate:</strong> The learning rate for the training process. This controls how much to change the model in response to the estimated error each time the model weights are updated.</li>
          <li><strong>Batch Size:</strong> The number of training examples utilized in one iteration. A larger batch size can lead to faster training but requires more memory.</li>
          <li><strong>Max Epochs:</strong> The number of times the learning algorithm will work through the entire training dataset. </li>

        </ul>
      </p>

    </>
  );
};

HelpDocsModelTraining.propTypes = {
  anchor: PropTypes.string,
};

export default HelpDocsModelTraining;
