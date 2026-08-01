import { describe, expect, it, mock } from 'bun:test';
import { fireEvent, render } from '@testing-library/react';
import { AnswerCardEditor } from '@/components/sub-agents/intake/components/answer-card-editor';

describe('AnswerCardEditor', () => {
  it('renders text area pre-populated with current text', () => {
    render(
      <AnswerCardEditor
        qid="q4_must_haves"
        topic="Must-haves"
        initialText="Python, PG"
        initialStatus="discussed"
        saving={false}
        onSave={mock()}
        onCancel={mock()}
      />,
    );
    const textarea = document.getElementById(
      'v2-intake-editor-textarea-q4_must_haves',
    ) as HTMLTextAreaElement;
    expect(textarea.value).toBe('Python, PG');
  });

  it('Save click invokes onSave with edited text + selected status', () => {
    const onSave = mock();
    render(
      <AnswerCardEditor
        qid="q4_must_haves"
        topic="Must-haves"
        initialText="Python"
        initialStatus="discussed"
        saving={false}
        onSave={onSave}
        onCancel={mock()}
      />,
    );
    const textarea = document.getElementById(
      'v2-intake-editor-textarea-q4_must_haves',
    ) as HTMLTextAreaElement;
    fireEvent.change(textarea, { target: { value: 'Python, PG, Kafka' } });
    const statusSel = document.getElementById(
      'v2-intake-editor-status-q4_must_haves',
    ) as HTMLSelectElement;
    fireEvent.change(statusSel, { target: { value: 'validated' } });
    fireEvent.click(
      document.getElementById('v2-intake-editor-save-btn-q4_must_haves') as HTMLButtonElement,
    );
    expect(onSave).toHaveBeenCalledWith({ text: 'Python, PG, Kafka', status: 'validated' });
  });

  it('Cancel click invokes onCancel without saving', () => {
    const onCancel = mock();
    const onSave = mock();
    render(
      <AnswerCardEditor
        qid="q1_role_overview"
        topic="Role overview"
        initialText="x"
        initialStatus="discussed"
        saving={false}
        onSave={onSave}
        onCancel={onCancel}
      />,
    );
    fireEvent.click(
      document.getElementById('v2-intake-editor-cancel-btn-q1_role_overview') as HTMLButtonElement,
    );
    expect(onCancel).toHaveBeenCalled();
    expect(onSave).not.toHaveBeenCalled();
  });

  it('Save button is disabled while saving=true', () => {
    render(
      <AnswerCardEditor
        qid="q1_role_overview"
        topic="Role overview"
        initialText="x"
        initialStatus="discussed"
        saving={true}
        onSave={mock()}
        onCancel={mock()}
      />,
    );
    const btn = document.getElementById(
      'v2-intake-editor-save-btn-q1_role_overview',
    ) as HTMLButtonElement;
    expect(btn.disabled).toBe(true);
  });

  it('Save is disabled when text is unchanged and status is unchanged', () => {
    render(
      <AnswerCardEditor
        qid="q1_role_overview"
        topic="Role overview"
        initialText="payments infra"
        initialStatus="discussed"
        saving={false}
        onSave={mock()}
        onCancel={mock()}
      />,
    );
    const btn = document.getElementById(
      'v2-intake-editor-save-btn-q1_role_overview',
    ) as HTMLButtonElement;
    expect(btn.disabled).toBe(true);
  });
});
