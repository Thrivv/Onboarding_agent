import React from 'react';
import { CheckCircle, X } from 'lucide-react';
import { NextDocumentCard } from '../cards/NextDocumentCard';
import { WelcomeOnboardingCard } from '../cards/WelcomeOnboardingCard';
import { TypewriterDisplay } from './TypewriterDisplay';
import { PlanningTimeline } from '../status/PlanningTimeline';
import { SuccessDisplay } from '../status/SuccessDisplay';
import { ValidationErrorDisplay } from '../status/ValidationErrorDisplay';
import logger from '../../../../utils/logger';

const MessageContent = (props) => {
  const {
    id, content, isWelcome, role, isProgress,
    isFatcaConfirmed, isUboConfirmed, isSelfDeclConfirmed,
    isCrossValidResult, crossValidPassed,
    isError, expectedDocuments, documentType, errorType,
    nextDocument, remainingDocuments, onUploadTrigger,
    currentStepId, extractedData,
    fatcaTrigger, pepTrigger, selfDeclTrigger, productPackageTrigger,
    moaAsTrigger, asKiTrigger,
  } = props;

  if (role === 'assistant' && (id?.includes('success') || extractedData || documentType)) {
    logger.log(`[MSG-CONTENT-DEBUG] ID: ${id}, hasExtractedData: ${!!extractedData}, docType: ${documentType}`);
    if (extractedData) logger.log('[MSG-CONTENT-DEBUG] Extracted Data Keys:', Object.keys(extractedData));
  }


  if (isWelcome) {
    return <WelcomeOnboardingCard content={content} />;
  }
  if (isProgress) {
    return <PlanningTimeline />;
  }
  if (isFatcaConfirmed || isUboConfirmed || isSelfDeclConfirmed) {
    return <SuccessDisplay message={content} />;
  }

  if (isError && (expectedDocuments || errorType === 'wrong_document_type' || errorType === 'unknown_document')) {
    return (
      <ValidationErrorDisplay
        message={content}
        expectedDocuments={expectedDocuments}
        uploadedType={documentType}
      />
    );
  }

  // ✅ FIX Issue 1 & 2: suppress the progression widget whenever a completion trigger
  // is active (FATCA / PEP / Self-Declaration) — those forms replace the widget.
  // moaAsTrigger/asKiTrigger added: same reasoning — when a message is about to
  // render the Authorised Signatories & Key Individuals card, the "Capture
  // Required" progression widget for identity docs is premature (the user
  // hasn't confirmed AS/Member roles yet) and shouldn't stack above it. This
  // only became reachable once bulk-upload results started carrying
  // nextDocument/remainingDocuments (previously they never did, so the two
  // cards never collided) — single-file messages were never observed to hit
  // this combination because their nextDocument/remaining_documents get
  // suppressed by a different, earlier check when a stage transition fires.
  const _hasTriggers = !!(fatcaTrigger || pepTrigger || selfDeclTrigger || productPackageTrigger || moaAsTrigger || asKiTrigger);
  const showNextDoc = (nextDocument || (remainingDocuments && remainingDocuments.length > 0)) && !isError;

  if (isCrossValidResult) {
    return (
      <div className={`p-4 rounded-xl flex items-center gap-3 border ${crossValidPassed ? 'bg-green-50 border-green-200 text-green-800' : 'bg-red-50 border-red-200 text-red-800'}`}>
        {crossValidPassed ? <CheckCircle className="h-5 w-5 text-green-600" /> : <X className="h-5 w-5 text-red-600" />}
        <p className="text-sm font-medium">{content}</p>
      </div>
    );
  }

  if (!content) return null;

  return (
    <div className="flex flex-col gap-4">
      {role === 'assistant' ? <TypewriterDisplay text={content} /> : <div className="whitespace-pre-wrap">{typeof content === 'string' ? content : JSON.stringify(content)}</div>}
      {(showNextDoc || (!nextDocument && !isError)) && role === 'assistant' && (
        <NextDocumentCard
          msgId={id}
          nextDoc={nextDocument}
          remainingDocs={remainingDocuments}
          onUploadTrigger={onUploadTrigger}
          currentStepId={currentStepId}
          hasTriggers={_hasTriggers}
          membersInfo={props.membersInfo}
          verifiedDocType={documentType}
          extractedData={extractedData}
        />
      )}
    </div>
  );
};


// ============================================================================
// GENERIC DISPLAY (FALLBACK)
// ============================================================================

export { MessageContent };
