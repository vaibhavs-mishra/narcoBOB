import { Navbar, NonIdealState, Tag } from "@blueprintjs/core";

export default function App() {
  return (
    <>
      <Navbar>
        <Navbar.Group>
          <Navbar.Heading>NarcoBob</Navbar.Heading>
          <Tag intent="warning" minimal>
            SIMULATED FEED
          </Tag>
        </Navbar.Group>
      </Navbar>
      <NonIdealState icon="map" title="Command centre" description="Waiting for the backend." />
    </>
  );
}
