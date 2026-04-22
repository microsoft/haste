// Copyright (c) Microsoft Corporation. All rights reserved.
// Licensed under the MIT License.
import {
    DefaultButton,
} from "@fluentui/react/lib/Button";


import SectionModal from "../SectionModal";
import proptypes from "prop-types";

const ModelCatalogAdditionalInfoModal = ({
    onClose,
    additionalInfo
}) => {

    ModelCatalogAdditionalInfoModal.propTypes = {
        onClose: proptypes.func.isRequired,
        additionalInfo: proptypes.object.isRequired,
    };

    return (
        <SectionModal
            title="Additional Info"
            body={
                <div className="modal-container p-1">
                    {Object.entries(additionalInfo).map(([key, value], idx) => (
                        <div key={key}>
                            <div className="row mb-1">
                                <div className="col-12 fw-semibold">{key}</div>
                            </div>
                            <div className="row mb-2">
                                <div className="col-12">{String(value)}</div>
                            </div>
                            {idx < Object.entries(additionalInfo).length - 1 && <hr />}
                        </div>
                    ))}
                    <div className="row mt-4">
                        <div className="col-12 d-flex justify-content-end">
                            <DefaultButton onClick={onClose}>Close</DefaultButton>
                        </div>
                    </div>
                </div>
            }
            onClose={onClose}
            icon="ProductCatalog"
        />
    );
};

export default ModelCatalogAdditionalInfoModal;
