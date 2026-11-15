import { Composition } from "remotion";
import { Video, DURACION } from "./Video";
export const Raiz = () => <Composition id="Tormentas" component={Video} durationInFrames={DURACION} fps={30} width={1080} height={1920} />;
