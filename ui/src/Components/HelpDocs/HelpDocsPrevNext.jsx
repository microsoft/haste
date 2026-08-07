import { Button } from "@fluentui/react-components";
import { FluentIcon } from "../../util/icons";
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
          <Button
            appearance="transparent"
            icon={<FluentIcon name="chevronleft" />}
            onClick={() => goTo(prevNext.previous.url)}
          >
            {prevNext.previous.title}
          </Button>
        ) : (
          <div />
        )}

        {prevNext.next ? (
          <Button
            appearance="transparent"
            icon={<FluentIcon name="chevronright" />}
            iconPosition="after"
            onClick={() => goTo(prevNext.next.url)}
          >
            {prevNext.next.title}
          </Button>
        ) : (
          <div />
        )}
      </div>
    </>
  );
};

export default HelpDocsPrevNext;
