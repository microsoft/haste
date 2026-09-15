// Copyright (c) Microsoft Corporation. All rights reserved.
// Licensed under the MIT License.
import {
    OverlayDrawer,
    DrawerHeader,
    DrawerHeaderTitle,
    DrawerBody,
    Button,
    tokens,
} from "@fluentui/react-components";
import { FluentIcon } from "../../util/icons";
import { useDrawerAnimation } from "../../util/useDrawerAnimation";
import proptypes from "prop-types";
import { catalogMetadataEntries } from "../ModelCatalogHelper";

const ModelCatalogAdditionalInfoModal = ({
    onClose,
    additionalInfo
}) => {
    const { open, requestClose } = useDrawerAnimation(onClose);
    const entries = catalogMetadataEntries(additionalInfo);

    return (
        <OverlayDrawer
            position="end"
            open={open}
            onOpenChange={(_, data) => {
                if (!data.open) requestClose();
            }}
            className="section-panel-drawer"
            style={{ "--fui-Drawer--size": "560px", maxWidth: "95vw" }}
        >
            <DrawerHeader className="section-panel-header">
                <DrawerHeaderTitle
                    action={
                        <Button
                            appearance="subtle"
                            icon={<FluentIcon name="Cancel" />}
                            aria-label="Close metadata panel"
                            onClick={requestClose}
                        />
                    }
                >
                    <span className="section-panel-title">
                        <FluentIcon name="Info" className="modal-icon" />
                        Metadata
                    </span>
                </DrawerHeaderTitle>
            </DrawerHeader>
            <DrawerBody>
                <div className="modal-container p-1">
                    {entries.map(([key, value], idx) => (
                        <div key={key}>
                            <div className="row mb-1">
                                <div className="col-12 fw-semibold">{key}</div>
                            </div>
                            <div className="row mb-2">
                                <div className="col-12">{value == null ? "--" : typeof value === "object" ? JSON.stringify(value) : String(value)}</div>
                            </div>
                            {idx < entries.length - 1 && (
                                <hr style={{ borderColor: tokens.colorNeutralStroke2 }} />
                            )}
                        </div>
                    ))}
                </div>
            </DrawerBody>
        </OverlayDrawer>
    );
};

ModelCatalogAdditionalInfoModal.propTypes = {
    onClose: proptypes.func.isRequired,
    additionalInfo: proptypes.any,
};

export default ModelCatalogAdditionalInfoModal;
