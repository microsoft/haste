import { Component } from "react";
import { Button } from "@fluentui/react-components";
import PropTypes from "prop-types";

export default class RouteErrorBoundary extends Component {
  static propTypes = { children: PropTypes.node };
  state = { failed: false };

  static getDerivedStateFromError() {
    return { failed: true };
  }

  render() {
    if (this.state.failed) {
      return (
        <div className="p-4" role="alert">
          <p>This page could not be loaded.</p>
          <Button onClick={() => window.location.reload()}>Reload page</Button>
        </div>
      );
    }
    return this.props.children;
  }
}