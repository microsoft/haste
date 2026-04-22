import { ActionButton } from "@fluentui/react";
import PropTypes from "prop-types";

const HelpDocsPrevNext = ({ prevNext }) => {
  HelpDocsPrevNext.propTypes = {
    prevNext: PropTypes.object.isRequired
  };

  const goTo = (url) => {
    navigate(url);
  };

  return (

    <>
      <hr className="mt-2 pb-2" />

      {/* Navigation between sections */}
      <div className="col-12 d-flex justify-content-between align-items-center">
        {prevNext.previous ? (
          <ActionButton
            iconProps={{ iconName: "chevronleft" }}
            onClick={() => goTo(prevNext.previous.url)}
          >
            {prevNext.previous.title}
          </ActionButton>
        ) : (
          <div />
        )}

        {prevNext.next ? (
          <ActionButton
            iconProps={{ iconName: "chevronright" }}
            styles={{
              flexContainer: { flexDirection: "row-reverse" },
            }}
            onClick={() => goTo(prevNext.next.url)}
          >
            {prevNext.next.title}
          </ActionButton>
        ) : (
          <div />
        )}
      </div>
    </>
  );
};

export default HelpDocsPrevNext;
