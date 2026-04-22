// Copyright (c) Microsoft Corporation. All rights reserved.
// Licensed under the MIT License.
// Loading Component
// This component displays a loading spinner with a "Loading" label. It is used to indicate
// that a background operation is in progress.

const ErrorMessage = ({ errorMessage }) => {
  return (
    <>
      {!!errorMessage && (
        <div className="error-message">{errorMessage}</div>
      )}
    </>
  );
};

export default ErrorMessage;
