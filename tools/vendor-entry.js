// Entry for the vendored editor bundle: everything the book editor needs, as window.PM.
// Add exports here and rebuild (see CONTRIBUTING.md, "Rebuilding the vendored editor").
export { EditorState, Plugin, PluginKey, Selection, TextSelection, NodeSelection } from "prosemirror-state";
export { EditorView, Decoration, DecorationSet } from "prosemirror-view";
export { Schema, Node, Fragment, Slice, DOMParser, DOMSerializer, Mark } from "prosemirror-model";
export { StepMap, Mapping } from "prosemirror-transform";
export {
  baseKeymap, toggleMark, setBlockType, wrapIn, lift, chainCommands, exitCode, joinBackward,
  selectParentNode, splitBlock, newlineInCode, createParagraphNear, liftEmptyBlock, deleteSelection,
} from "prosemirror-commands";
export { keymap } from "prosemirror-keymap";
export { history, undo, redo } from "prosemirror-history";
export {
  inputRules, InputRule, wrappingInputRule, textblockTypeInputRule, ellipsis, emDash,
  smartQuotes, undoInputRule,
} from "prosemirror-inputrules";
export { dropCursor } from "prosemirror-dropcursor";
export { gapCursor } from "prosemirror-gapcursor";
